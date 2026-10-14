"""Executive synthesis: the AI layer that turns raw findings into a
narrative. Runs on gemini-flash-latest, with a deterministic fallback so
the report is always complete even if the model call fails."""

from __future__ import annotations

from typing import Any

from . import config
from .llm import call_gemini
from .models import Finding

_PROMPT = """Write the summary block of an automated website QA report.

Target: {url}
Severity counts: {counts}. Core Web Vitals source: {vitals_source}.

FINDINGS (severity | category | title | detail):
{findings}

Style rules, follow them exactly:
- Plain English, no marketing language, no filler.
- "summary" is TWO sentences maximum. First sentence: the single biggest problem and
  what it costs the site owner. Second: the overall state of the page.
- "top_risks": at most 5 items, each one short imperative line under 18 words, most
  severe first, naming a concrete consequence.
- Banned words and phrases: furthermore, moreover, overall, it is worth noting,
  comprehensive, robust, leverage, seamlessly, delve, landscape, testament, crucial.
- Do not invent findings that are not in the list. No markdown.

Return ONLY JSON:
{{"summary": "...", "top_risks": ["...", "..."]}}"""


def _deterministic(findings: list[Finding], counts: dict[str, int]) -> dict[str, Any]:
    top = [f"{f.title} — {f.detail[:150]}" for f in findings[:5]] or ["No material risks detected."]
    critical = counts.get("critical", 0)
    high = counts.get("high", 0)
    summary = (
        f"{findings[0].title} is the most urgent of {len(findings)} findings"
        f" ({critical} critical, {high} high)."
        if findings
        else "No issues were recorded for this page."
    )
    return {"summary": summary, "top_risks": top, "source": "deterministic"}


async def synthesize(
    url: str, findings: list[Finding], counts: dict[str, int], vitals: dict[str, Any], log
) -> dict[str, Any]:
    if not findings:
        return _deterministic(findings, counts)
    lines = "\n".join(
        f"- {f.severity} | {f.category} | {f.title} | {f.detail[:180]}" for f in findings[:40]
    )
    prompt = _PROMPT.format(
        url=url, counts=counts, vitals_source=vitals.get("source", "n/a"), findings=lines
    )
    try:
        log(f"asking {config.GEMINI_MODEL} for the executive summary")
        data = await call_gemini(prompt, max_tokens=1500)
        summary = str(data.get("summary", "")).strip()
        risks = [str(r).strip() for r in data.get("top_risks", []) if str(r).strip()][:5]
        if not summary:
            raise ValueError("empty summary")
        return {"summary": summary, "top_risks": risks or _deterministic(findings, counts)["top_risks"],
                "source": config.GEMINI_MODEL}
    except Exception as exc:  # noqa: BLE001 - always degrade to a usable report
        log(f"synthesis degraded to deterministic summary ({exc})")
        return _deterministic(findings, counts)
