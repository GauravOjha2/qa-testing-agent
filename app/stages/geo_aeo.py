"""Stage 5 — GEO/AEO (generative-engine optimisation) + AI visual review.

Runs entirely on gemini-flash-latest. Two jobs in one multimodal call:

  1. GEO/AEO: scrape the page's ground truth (title, meta, headings,
     JSON-LD, visible copy), ask realistic buyer questions, answer them
     *strictly from that ground truth*, and flag the questions an AI
     answer engine would get wrong — i.e. real buyer intent the page
     does not actually satisfy.
  2. Visual review: the same call receives the desktop screenshot and
     reports layout/hierarchy problems a human reviewer would catch.

Reproducibility: temperature 0.2, fixed question bank folded into the
prompt, and deterministic finding IDs, so repeat scans dedupe to the
same finding set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import Browser

from .. import config
from ..llm import LLMUnavailable, call_gemini
from ..models import Finding, finding_id
from ..ratelimit import RateLimiter
from .browser import goto_polite, new_context

_GROUND_TRUTH_JS = """() => {
  const txt = (sel) => (document.querySelector(sel) || {}).innerText || '';
  const meta = (n) => { const m = document.querySelector(`meta[name="${n}"], meta[property="${n}"]`); return m ? m.content : ''; };
  const ld = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
    .map(s => s.textContent.slice(0, 1200));
  const main = document.querySelector('main') || document.body;
  return {
    title: document.title,
    description: meta('description') || meta('og:description'),
    ogTitle: meta('og:title'),
    canonical: (document.querySelector('link[rel=canonical]') || {}).href || '',
    h1: Array.from(document.querySelectorAll('h1')).map(h => h.innerText.trim()).slice(0, 3),
    h2: Array.from(document.querySelectorAll('h2')).map(h => h.innerText.trim()).slice(0, 12),
    h3: Array.from(document.querySelectorAll('h3')).map(h => h.innerText.trim()).slice(0, 12),
    jsonLd: ld,
    ctaText: Array.from(document.querySelectorAll('button, a[role=button], .btn, [class*=cta]'))
      .map(b => b.innerText.trim()).filter(Boolean).slice(0, 10),
    priceHits: (main.innerText.match(/[$€£₹]\\s?\\d[\\d.,]*|\\b\\d+\\s?(USD|EUR|INR)\\b/g) || []).slice(0, 10),
    faqPresent: !!document.querySelector('[itemtype*="FAQPage"], details, [class*=faq i]'),
    text: main.innerText.replace(/\\n{3,}/g, '\\n\\n').slice(0, %d)
  };
}""" % config.MAX_GROUND_TRUTH_CHARS

_BUYER_QUESTIONS = [
    "What exactly does this product do, in one sentence?",
    "How much does it cost, and what pricing tiers exist?",
    "Who is it for — what company size or role?",
    "What are the three strongest capabilities it claims?",
    "How does someone get started or sign up?",
    "How does it differ from the obvious alternatives?",
]

_PROMPT = """You are a buyer-side QA analyst auditing a single marketing page.

BUYER QUESTIONS to test (answer each strictly from PAGE GROUND TRUTH below):
{questions}

PAGE GROUND TRUTH (verbatim from {url}):
---8<---
title: {title}
meta description: {description}
h1: {h1}
h2: {h2}
h3: {h3}
json-ld blocks: {json_ld}
visible CTA labels: {ctas}
currency/price strings found on page: {prices}
FAQ/schema markup present: {faq}
body copy:
{text}
---8<---

Also review the attached desktop screenshot as a human QA reviewer.

Return ONLY JSON in exactly this shape:
{{
  "questions": [
    {{"question": "...", "answer_from_page": "...", "grounded": true,
      "gap": "empty string when grounded, else the specific missing fact",
      "risk": "what an AI answer engine would wrongly tell a buyer"}}
  ],
  "wrong_claims": [
    {{"claim": "...", "why_wrong": "...", "severity": "high|medium|low",
      "fix": "concrete change to the page"}}
  ],
  "visual_issues": [
    {{"severity": "critical|high|medium|low", "title": "...", "detail": "...",
      "recommendation": "..."}}
  ]
}}

Rules: never invent facts that are not in the ground truth; if the page does
not state a price, say so and treat it as a gap. Max 6 questions, 5 wrong
claims, 5 visual issues. Be specific and terse."""


def _sev(value: str, default: str = "medium") -> str:
    value = (value or "").lower().strip()
    return value if value in {"critical", "high", "medium", "low", "info"} else default


async def run(
    browser: Browser,
    url: str,
    limiter: RateLimiter,
    log,
    screenshot_thumb: Path | None,
) -> tuple[list[Finding], dict[str, Any]]:
    context = await new_context(browser, config.VIEWPORTS["desktop"])
    try:
        page = await context.new_page()
        await goto_polite(page, url, limiter)
        await page.wait_for_timeout(1000)
        truth = await page.evaluate(_GROUND_TRUTH_JS)
    finally:
        await context.close()

    log(
        f"ground truth captured: {len(truth.get('text',''))} chars, "
        f"{len(truth.get('jsonLd', []))} JSON-LD block(s), FAQ markup: {truth.get('faqPresent')}"
    )

    findings: list[Finding] = []
    analysis: dict[str, Any] = {"ground_truth": {k: v for k, v in truth.items() if k != "text"}}

    prompt = _PROMPT.format(
        questions="\n".join(f"  {i+1}. {q}" for i, q in enumerate(_BUYER_QUESTIONS)),
        url=url,
        title=truth.get("title", ""),
        description=truth.get("description", ""),
        h1=" | ".join(truth.get("h1", [])),
        h2=" | ".join(truth.get("h2", [])),
        h3=" | ".join(truth.get("h3", [])),
        json_ld=" ".join(truth.get("jsonLd", []))[:1500] or "none",
        ctas=" | ".join(truth.get("ctaText", [])),
        prices=" | ".join(truth.get("priceHits", [])) or "none found",
        faq=truth.get("faqPresent"),
        text=truth.get("text", ""),
    )

    image = screenshot_thumb.read_bytes() if screenshot_thumb and screenshot_thumb.is_file() else None
    try:
        log(f"calling {config.GEMINI_MODEL} (multimodal: page text + desktop screenshot)")
        data = await call_gemini(prompt, image_bytes=image)
    except LLMUnavailable as exc:
        log(f"AI layer disabled: {exc}")
        analysis["llm_status"] = "disabled — GEMINI_API_KEY not set"
        findings.append(
            Finding(
                id=finding_id("geo_aeo", "llm-disabled"),
                category="geo_aeo",
                severity="info",
                title="AI answer-engine check skipped (no API key)",
                detail=(
                    "The GEO/AEO and visual-review layer runs on gemini-flash-latest and needs "
                    "GEMINI_API_KEY. Without it the page was still scraped and screenshotted, "
                    "but no AI-answer analysis was produced."
                ),
                evidence={"model": config.GEMINI_MODEL},
                recommendation="Set GEMINI_API_KEY to enable the AI layers.",
            )
        )
        return findings, analysis
    except Exception as exc:  # noqa: BLE001 - degrade, never fail the scan
        log(f"AI layer degraded: {exc}")
        analysis["llm_status"] = f"error — {exc}"
        return findings, analysis

    analysis["llm_status"] = "ok"
    analysis["questions"] = data.get("questions", [])
    analysis["wrong_claims"] = data.get("wrong_claims", [])
    analysis["visual_issues"] = data.get("visual_issues", [])

    for q in data.get("questions", []):
        if q.get("grounded") is not False:
            continue
        findings.append(
            Finding(
                id=finding_id("geo_aeo", "ungrounded-question", q.get("question", "")[:80]),
                category="geo_aeo",
                severity="high" if "cost" in (q.get("question", "").lower()) else "medium",
                title=f"AI answer engines cannot answer: “{q.get('question', '')}”",
                detail=(
                    f"Page answer found: {q.get('answer_from_page', '') or 'nothing on the page.'} "
                    f"Missing fact: {q.get('gap', '')}. "
                    f"Likely AI-answer failure: {q.get('risk', '')}"
                ),
                evidence={"question": q.get("question", ""), "gap": q.get("gap", ""),
                          "risk": q.get("risk", "")},
                recommendation=(
                    "Add the missing fact in plain, quotable prose (and in JSON-LD/FAQ schema) "
                    "so answer engines can cite the page instead of guessing."
                ),
            )
        )

    for claim in data.get("wrong_claims", []):
        findings.append(
            Finding(
                id=finding_id("geo_aeo", "wrong-claim", claim.get("claim", "")[:80]),
                category="geo_aeo",
                severity=_sev(claim.get("severity")),
                title=f"Claim an AI engine would get wrong: {claim.get('claim', '')[:90]}",
                detail=f"{claim.get('why_wrong', '')}",
                evidence={"claim": claim.get("claim", "")},
                recommendation=claim.get("fix", ""),
            )
        )

    for issue in data.get("visual_issues", []):
        findings.append(
            Finding(
                id=finding_id("visual", "ai-review", issue.get("title", "")[:80]),
                category="visual",
                severity=_sev(issue.get("severity")),
                title=issue.get("title", "Visual issue"),
                detail=issue.get("detail", ""),
                evidence={
                    "source": f"{config.GEMINI_MODEL} visual review",
                    # repo-relative so no host filesystem paths leak into the report
                    "screenshot": (
                        str(screenshot_thumb.relative_to(config.REPO_ROOT))
                        if screenshot_thumb and screenshot_thumb.is_file() else ""
                    ),
                },
                recommendation=issue.get("recommendation", ""),
            )
        )

    log(
        f"AI review: {len(data.get('questions', []))} questions, "
        f"{len(data.get('wrong_claims', []))} wrong-claim risks, "
        f"{len(data.get('visual_issues', []))} visual issues"
    )
    return findings, analysis
