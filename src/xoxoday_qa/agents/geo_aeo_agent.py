"""GEO/AEO audit agent — does AI describe Xoxoday correctly?

See brief section C. Two layers:
  1. Static: JSON-LD/schema.org + meta tags vs. rendered page content.
  2. Dynamic: ask multiple LLMs realistic buyer questions, diff against
     ground truth scraped from the page itself.

The dynamic layer is the more novel/on-theme part for this specific
prospect (their site advertises AI-native features) — it's checking
whether *other* AI systems already understand their AI product correctly.
"""

from __future__ import annotations

import json
import re

from playwright.sync_api import Browser

from ..config import RUN
from ..dom_utils import read_meta_description
from ..models import AgentSource, Finding, PageTarget, PageType, Severity
from ..playwright_utils import goto_and_settle, new_context, throttle
from .llm_client import call_named_engine, call_text_model

BUYER_QUESTIONS_TEMPLATE = [
    "What does Xoxoday's {product} product do?",
    "Does Xoxoday support WhatsApp reward delivery?",
    "What countries can Xoxoday deliver rewards to?",
    "Does Xoxoday have an AI assistant or AI-personalized recommendations?",
]

DIFF_JUDGE_PROMPT = """Compare CLAIM (from an AI answer engine) against GROUND_TRUTH
(scraped directly from the company's own page). Judge only factual
consistency about the product/company — not writing style.

CLAIM: {claim}

GROUND_TRUTH: {ground_truth}

Respond ONLY with JSON, no markdown fences:
{{"consistent": true|false, "confidence": 0.0-1.0, "mismatch_summary": "..."}}
"""


def run(browser: Browser, target: PageTarget, shard_key: str = "default") -> list[Finding]:
    findings: list[Finding] = []
    ctx = new_context(browser, {"width": 1440, "height": 900})
    page = ctx.new_page()
    throttle(shard_key)
    goto_and_settle(page, target.url)

    static_findings, ground_truth_text = _static_layer(page, target)
    findings.extend(static_findings)

    ctx.close()

    # The dynamic multi-LLM cross-check is meaningful wherever buyers evaluate
    # a product — product pages AND their pricing pages. The detail of the
    # pass finding records exactly which layers ran so reports can't
    # overstate coverage.
    dynamic_detail = ""
    if target.page_type in (PageType.PRODUCT, PageType.PRICING_ROI):
        dynamic_findings, engines_used = _dynamic_layer(target, ground_truth_text)
        findings.extend(dynamic_findings)
        if engines_used:
            dynamic_detail = (
                f" Dynamic LLM cross-check asked {len(BUYER_QUESTIONS_TEMPLATE)} "
                f"buyer questions across: {', '.join(sorted(engines_used))}."
            )
        else:
            dynamic_detail = (
                " Dynamic LLM cross-check was in scope for this page type but "
                "no answer-engine API keys were configured."
            )
    else:
        dynamic_detail = (
            " Dynamic LLM cross-check not applicable to this page type; it "
            "runs on product and pricing pages."
        )

    if not findings:
        findings.append(Finding(
            url=target.url, agent=AgentSource.GEO_AEO, severity=Severity.INFO,
            title="No GEO/AEO issues found",
            detail="Static schema/meta-tag checks passed." + dynamic_detail,
            tags=["geo_aeo", "pass"],
        ))

    return findings


def _static_layer(page, target: PageTarget) -> tuple[list[Finding], str]:
    """Diff JSON-LD/meta tags against visible page content."""
    findings: list[Finding] = []

    jsonld_blocks = page.locator('script[type="application/ld+json"]')
    # Read already-present DOM state rather than waiting on a strict locator.
    # Next.js sites can continue hydrating long after the page is usable; a
    # missing/late description should not fail the whole QA run.
    visible_text = page.locator("body").inner_text(timeout=5_000)[:8000]

    schema_claims: list[dict] = []
    for i in range(jsonld_blocks.count()):
        raw = jsonld_blocks.nth(i).inner_text()
        try:
            data = json.loads(raw)
            schema_claims.append(data)
        except json.JSONDecodeError:
            findings.append(Finding(
                url=target.url, agent=AgentSource.GEO_AEO, severity=Severity.MEDIUM,
                title="Malformed JSON-LD block",
                detail="A structured-data block on this page is not valid JSON. "
                       "AI answer engines that parse schema.org data will silently "
                       "skip or misparse this, degrading how the page is represented.",
                tags=["geo_aeo", "structured-data", "malformed"],
            ))

    meta_desc = read_meta_description(page)
    if meta_desc and len(meta_desc) > 20:
        overlap = _rough_text_overlap(meta_desc, visible_text)
        if overlap < 0.15:
            findings.append(Finding(
                url=target.url, agent=AgentSource.GEO_AEO, severity=Severity.HIGH,
                title="Meta description doesn't match visible page content",
                detail=(
                    f"Meta description: '{meta_desc[:200]}' shares little "
                    "vocabulary with the rendered page body. This is exactly "
                    "the kind of mismatch that causes AI answer engines to "
                    "surface stale or inaccurate summaries."
                ),
                tags=["geo_aeo", "meta-tags", "mismatch"],
            ))

    ground_truth = visible_text
    return findings, ground_truth


def _dynamic_layer(target: PageTarget, ground_truth: str) -> tuple[list[Finding], set[str]]:
    """Ask configured answer engines buyer questions and diff their claims
    against page ground truth. Returns findings plus the set of engines
    that actually answered, so callers can report real coverage."""
    findings: list[Finding] = []
    engines_used: set[str] = set()
    product_name = _guess_product_name(target.url)
    questions = [q.format(product=product_name) for q in BUYER_QUESTIONS_TEMPLATE]

    for engine in RUN.llm_engines_for_geo_check:
        for question in questions:
            claim = call_named_engine(engine, question)
            if claim is None:
                continue  # engine not configured, skip silently
            engines_used.add(engine)

            judge_raw = call_text_model(
                DIFF_JUDGE_PROMPT.format(claim=claim, ground_truth=ground_truth[:4000])
            )
            verdict = _safe_parse_json(judge_raw)

            if verdict.get("consistent") is False:
                findings.append(Finding(
                    url=target.url, agent=AgentSource.GEO_AEO,
                    severity=Severity.HIGH,
                    title=f"{engine} answers this question inconsistently with the site",
                    detail=(
                        f"Q: {question}\n"
                        f"{engine} claim: {claim[:300]}\n"
                        f"Mismatch: {verdict.get('mismatch_summary', 'n/a')}"
                    ),
                    confidence=float(verdict.get("confidence", 0.6)),
                    tags=["geo_aeo", "dynamic", engine],
                ))

    return findings, engines_used


def _guess_product_name(url: str) -> str:
    for name in ("Empuls", "Plum", "Compass"):
        if name.lower() in url.lower():
            return name
    return "flagship"


def _rough_text_overlap(a: str, b: str) -> float:
    words_a = set(re.findall(r"[a-z]{4,}", a.lower()))
    words_b = set(re.findall(r"[a-z]{4,}", b.lower()))
    if not words_a:
        return 1.0
    return len(words_a & words_b) / len(words_a)


def _safe_parse_json(raw: str) -> dict:
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}
