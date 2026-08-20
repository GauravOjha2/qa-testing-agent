"""Thin wrapper around whichever LLM provider is configured.

Every specialist agent goes through here rather than calling an SDK
directly, for two reasons:
  1. One place to swap Gemini <-> Claude, or add a provider.
  2. QA_LOCAL_MODE support: with no API keys configured, calls return a
      clearly-labeled mock so the whole pipeline (crawl -> agents ->
      synthesis -> report) can be exercised end-to-end without any
     credentials, to verify the architecture before spending API budget
     on a real run.
"""

from __future__ import annotations

import os

from ..config import RUN

_MOCK_VISION_RESPONSE = '{"issues": []}'
_MOCK_TEXT_RESPONSE = "[MOCK MODE — no LLM API key configured. Set GEMINI_API_KEY or ANTHROPIC_API_KEY.]"


def _has_any_llm_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))


def call_vision_model(prompt: str, image_b64: str, context: str = "") -> str:
    if not _has_any_llm_key():
        return _MOCK_VISION_RESPONSE

    if os.environ.get("ANTHROPIC_API_KEY"):
        return _call_claude_vision(prompt, image_b64, context)
    return _call_gemini_vision(prompt, image_b64, context)


def call_text_model(prompt: str) -> str:
    if not _has_any_llm_key():
        return _MOCK_TEXT_RESPONSE

    if os.environ.get("ANTHROPIC_API_KEY"):
        return _call_claude_text(prompt)
    return _call_gemini_text(prompt)


def call_named_engine(engine: str, prompt: str) -> str | None:
    """Used by the GEO/AEO agent to cross-check specific answer engines.

    Returns None (not an error string) if that engine's key isn't
    configured, so the caller can skip it cleanly rather than logging a
    fake finding.
    """
    key_env = {
        "gemini": "GEMINI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "perplexity": "PERPLEXITY_API_KEY",
    }.get(engine)
    if not key_env or not os.environ.get(key_env):
        return None

    if engine == "gemini":
        return _call_gemini_text(prompt)
    if engine == "claude":
        return _call_claude_text(prompt)
    if engine == "perplexity":
        return _call_perplexity_text(prompt)
    return None


# --- Provider implementations -------------------------------------------
# Each is intentionally isolated so a missing SDK/dependency for one
# provider doesn't break the others. Import errors are raised lazily,
# inside the function, not at module load.

def _call_claude_vision(prompt: str, image_b64: str, context: str) -> str:
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": f"{context}\n\n{prompt}"},
            ],
        }],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _call_claude_text(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _call_gemini_vision(prompt: str, image_b64: str, context: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-flash-latest")
    import base64
    image_bytes = base64.b64decode(image_b64)
    resp = model.generate_content([
        f"{context}\n\n{prompt}",
        {"mime_type": "image/png", "data": image_bytes},
    ])
    return resp.text


def _call_gemini_text(prompt: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-flash-latest")
    resp = model.generate_content(prompt)
    return resp.text


def _call_perplexity_text(prompt: str) -> str:
    import httpx
    resp = httpx.post(
        "https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['PERPLEXITY_API_KEY']}"},
        json={"model": "sonar", "messages": [{"role": "user", "content": prompt}]},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
