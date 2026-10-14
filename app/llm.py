"""Single AI client for the whole product.

Hard rule: every AI layer runs on `gemini-flash-latest` and nothing else.
One GEMINI_API_KEY drives all calls. Requests use the REST endpoint via
httpx so no heavyweight SDK is required. JSON-mode output, bounded
retries on 429/5xx, and defensive parsing so a malformed model reply
degrades the stage instead of crashing the scan.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from typing import Any

import httpx

from . import config


class LLMUnavailable(RuntimeError):
    """Raised when no GEMINI_API_KEY is configured."""


def available() -> bool:
    return bool(config.gemini_api_key())


def _extract_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise


async def call_gemini(
    prompt: str,
    *,
    image_bytes: bytes | None = None,
    image_mime: str = "image/jpeg",
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> Any:
    """Call gemini-flash-latest and return parsed JSON.

    With an image attached this is a multimodal call (visual review);
    without one it is text-only (GEO/AEO, synthesis). Same model either way.
    """
    key = config.gemini_api_key()
    if not key:
        raise LLMUnavailable("GEMINI_API_KEY is not configured")

    url = f"{config.GEMINI_API_BASE}/models/{config.GEMINI_MODEL}:generateContent"
    parts: list[dict[str, Any]] = [{"text": prompt}]
    if image_bytes:
        parts.append(
            {
                "inline_data": {
                    "mime_type": image_mime,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            }
        )
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }

    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
        for attempt in range(config.LLM_MAX_RETRIES):
            try:
                resp = await client.post(url, params={"key": key}, json=payload)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"transient {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                data = resp.json()
                text = "".join(
                    part.get("text", "")
                    for part in data["candidates"][0]["content"]["parts"]
                )
                if not text.strip():
                    raise ValueError("empty model response")
                return _extract_json(text)
            except Exception as exc:  # noqa: BLE001 - deliberate retry-all
                last_error = exc
                if attempt < config.LLM_MAX_RETRIES - 1:
                    await asyncio.sleep(2**attempt * 1.5)
    raise RuntimeError(f"gemini call failed after retries: {last_error}")
