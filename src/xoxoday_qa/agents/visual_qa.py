"""Visual & brand QA agent.

AI judge, not pixel-diff — see brief section A. Screenshots each page at
mobile/tablet/desktop, then passes each image to a multimodal model with a
structured rubric. The rubric is deliberately narrow (layout breaks,
overlap, brand consistency, i18n text overflow) rather than "does this look
good," because open-ended aesthetic judgment from a vision model is noisy;
a bounded rubric is not.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from playwright.sync_api import Browser

from ..models import AgentSource, Finding, PageTarget, Severity
from ..playwright_utils import screenshot_at_breakpoints
from .llm_client import call_vision_model, is_mock_mode

RUBRIC_PROMPT = """You are a visual QA judge for a B2B SaaS marketing/product site.
You will be shown a full-page screenshot at a specific viewport width.
Ignore ordinary content differences (copy changes, new blog posts, etc).

Check ONLY for:
1. Broken layout: elements overlapping, text clipped or cut off, unstyled
   raw HTML, broken image icons, elements rendering outside the viewport.
2. Text overflow: this is a localized/multilingual site — translated
   strings (esp. German, and other longer-than-English languages) can
   overflow a container sized for English. Flag any text that appears
   truncated, wrapped awkwardly across a button/card boundary, or
   overflowing its visual container.
3. Brand consistency: obviously wrong logo, jarring color/spacing breaks
   from what looks like the site's established design system.
4. Any other clearly-broken rendering (e.g. a component that looks like
   it errored, a blank section where content should be).

Respond ONLY with JSON, no markdown fences, matching this schema:
{
  "issues": [
    {"category": "layout|overflow|brand|other", "severity": "critical|high|medium|low",
     "description": "...", "confidence": 0.0-1.0}
  ]
}
If nothing is wrong, return {"issues": []}.
"""

_SEVERITY_MAP = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
}


def run(browser: Browser, target: PageTarget, out_dir: str, shard_key: str = "default") -> list[Finding]:
    findings: list[Finding] = []
    screenshots = screenshot_at_breakpoints(browser, target.url, out_dir, shard_key)

    for breakpoint_name, path in screenshots.items():
        with open(path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        raw_response = call_vision_model(
            prompt=RUBRIC_PROMPT,
            image_b64=image_b64,
            context=f"URL: {target.url}\nViewport: {breakpoint_name}\nLocale: {target.locale}",
        )
        parsed = _safe_parse_json(raw_response)

        for issue in parsed.get("issues", []):
            findings.append(Finding(
                url=target.url,
                agent=AgentSource.VISUAL_QA,
                severity=_SEVERITY_MAP.get(issue.get("severity", "low"), Severity.LOW),
                title=f"[{breakpoint_name}] {issue.get('category', 'visual')} issue",
                detail=issue.get("description", ""),
                evidence_uri=path,
                confidence=float(issue.get("confidence", 0.7)),
                tags=["visual", breakpoint_name, issue.get("category", "other"), target.locale],
            ))

    if not findings:
        detail = "Passed rubric at all 3 breakpoints."
        tags = ["visual", "pass"]
        if is_mock_mode():
            # No API key configured: the vision judgment did NOT run.
            # Say so explicitly so reports can't overstate coverage.
            detail += (
                " [MOCK MODE — no LLM API key configured; screenshots were "
                "captured but no vision-model judgment was performed.]"
            )
            tags.append("mock")
        findings.append(Finding(
            url=target.url, agent=AgentSource.VISUAL_QA, severity=Severity.INFO,
            title="No visual issues found", detail=detail,
            tags=tags,
        ))

    return findings


def _safe_parse_json(raw: str) -> dict[str, Any]:
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"issues": []}
