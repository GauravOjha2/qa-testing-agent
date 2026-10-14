"""Stage 2 — axe-core WCAG 2.2 A/AA accessibility audit."""

from __future__ import annotations

from playwright.async_api import Browser

from .. import config
from ..models import Finding, finding_id
from ..ratelimit import RateLimiter
from .browser import goto_polite, new_context

_AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
_IMPACT_MAP = {"critical": "critical", "serious": "high", "moderate": "medium", "minor": "low"}


async def run(browser: Browser, url: str, limiter: RateLimiter, log) -> list[Finding]:
    if not config.AXE_PATH.is_file():
        raise FileNotFoundError(f"axe-core bundle missing at {config.AXE_PATH}")

    context = await new_context(browser, config.VIEWPORTS["desktop"])
    try:
        page = await context.new_page()
        await goto_polite(page, url, limiter)
        await page.wait_for_timeout(800)
        log("injecting axe-core 4.x, running WCAG 2.2 A/AA ruleset")
        await page.add_script_tag(path=str(config.AXE_PATH))
        raw = await page.evaluate(
            """async (tags) => {
              const res = await axe.run(document, {
                runOnly: {type: 'tag', values: tags},
                resultTypes: ['violations']
              });
              return res.violations.map(v => ({
                id: v.id, impact: v.impact, help: v.help, helpUrl: v.helpUrl,
                description: v.description,
                nodes: v.nodes.slice(0, %d).map(n => ({
                  target: n.target.join(' '),
                  html: (n.html || '').slice(0, 220),
                  summary: (n.failureSummary || '').split('\\n').slice(0, 2).join(' ')
                }))
              }));
            }""" % config.MAX_AXE_NODES_PER_RULE,
            _AXE_TAGS,
        )
    finally:
        await context.close()

    findings: list[Finding] = []
    node_total = 0
    for v in raw:
        severity = _IMPACT_MAP.get(v.get("impact") or "minor", "low")
        node_total += len(v.get("nodes", []))
        first = v["nodes"][0] if v.get("nodes") else {}
        findings.append(
            Finding(
                id=finding_id("accessibility", v["id"], first.get("target", "")),
                category="accessibility",
                severity=severity,
                title=f"{v['help']} ({v['id']})",
                detail=v.get("description", ""),
                evidence={
                    "rule": v["id"],
                    "wcag": v.get("helpUrl", ""),
                    "instances": len(v.get("nodes", [])),
                    "selector": first.get("target", ""),
                    "snippet": first.get("html", ""),
                    "failure": first.get("summary", ""),
                },
                # The axe node failure summary is a concrete "Fix any of the
                # following..." instruction — far more useful than the rule title.
                recommendation=(first.get("summary") or v.get("help", "")),
            )
        )
    log(f"axe: {len(findings)} violation rules, {node_total} evidence nodes kept")
    return findings
