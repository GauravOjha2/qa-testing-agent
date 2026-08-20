"""Accessibility + performance + silent-failures agent.

See brief section D. Three checks per page:
  1. WCAG 2.2 AA via axe-core (injected into the page, runs in-browser).
  2. Core Web Vitals (LCP/INP/CLS) via Lighthouse, run as a subprocess.
  3. Silent failures via the PageMonitor attached during page load —
     the network/console monitor is the differentiator per the brief:
     things that don't 404 and a human clicking around would miss.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import Browser

from ..models import AgentSource, Finding, PageTarget, Severity
from ..playwright_utils import PageMonitor, goto_and_settle, new_context, throttle

AXE_CORE_CDN = "https://unpkg.com/axe-core@4.10.0/axe.min.js"
AXE_CORE_LOCAL_PATH = Path(__file__).resolve().parents[3] / "node_modules" / "axe-core" / "axe.min.js"

_IMPACT_MAP = {
    "critical": Severity.CRITICAL,
    "serious": Severity.HIGH,
    "moderate": Severity.MEDIUM,
    "minor": Severity.LOW,
}

# Core Web Vitals "good" thresholds (Google's published values).
CWV_THRESHOLDS = {
    "largest-contentful-paint": {"good_ms": 2500, "label": "LCP"},
    "cumulative-layout-shift": {"good_ms": 0.1, "label": "CLS"},  # unitless score, not ms
    "interaction-to-next-paint": {"good_ms": 200, "label": "INP"},
}


def run(browser: Browser, target: PageTarget, shard_key: str = "default") -> list[Finding]:
    findings: list[Finding] = []
    monitor = PageMonitor()

    ctx = new_context(browser, {"width": 1440, "height": 900})
    page = ctx.new_page()
    monitor.attach(page)

    throttle(shard_key)
    goto_and_settle(page, target.url)

    findings.extend(_run_axe(page, target))
    findings.extend(_silent_failures_from_monitor(monitor, target))

    ctx.close()

    findings.extend(_run_lighthouse(target))

    if not findings:
        findings.append(Finding(
            url=target.url, agent=AgentSource.A11Y_PERF, severity=Severity.INFO,
            title="No a11y/perf/silent-failure issues found", tags=["a11y_perf", "pass"],
        ))

    return findings


def _run_axe(page, target: PageTarget) -> list[Finding]:
    findings: list[Finding] = []
    try:
        if AXE_CORE_LOCAL_PATH.exists():
            page.add_script_tag(path=str(AXE_CORE_LOCAL_PATH))
        else:
            page.add_script_tag(url=AXE_CORE_CDN)
        results_json = page.evaluate("""
            async () => {
                const results = await axe.run(document, {
                    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag22aa'] }
                });
                return JSON.stringify(results.violations);
            }
        """)
        violations = json.loads(results_json)
    except Exception as e:
        return [Finding(
            url=target.url, agent=AgentSource.A11Y_PERF, severity=Severity.LOW,
            title="axe-core scan failed to run", detail=str(e), tags=["a11y", "scan-error"],
        )]

    for v in violations:
        findings.append(Finding(
            url=target.url, agent=AgentSource.A11Y_PERF,
            severity=_IMPACT_MAP.get(v.get("impact"), Severity.MEDIUM),
            title=f"A11y: {v.get('id')} — {v.get('help')}",
            detail=f"{v.get('description', '')} Affects {len(v.get('nodes', []))} element(s). {v.get('helpUrl', '')}",
            tags=["a11y", "wcag", v.get("id", "")],
            raw={"nodes": [n.get("target") for n in v.get("nodes", [])][:5]},
        ))

    return findings


def _silent_failures_from_monitor(monitor: PageMonitor, target: PageTarget) -> list[Finding]:
    findings: list[Finding] = []

    for err in monitor.console_errors[:20]:  # cap noise per page
        findings.append(Finding(
            url=target.url, agent=AgentSource.A11Y_PERF, severity=Severity.MEDIUM,
            title="JS console error (no visible break)",
            detail=err, tags=["silent-failure", "console-error"],
        ))

    for failure in monitor.network_failures[:20]:
        kind = failure.get("kind")
        severity = Severity.HIGH if kind == "silent_error_payload" else Severity.MEDIUM
        findings.append(Finding(
            url=target.url, agent=AgentSource.A11Y_PERF, severity=severity,
            title=f"Silent network failure: {kind}",
            detail=f"{failure.get('url')} (status={failure.get('status')})",
            tags=["silent-failure", kind or "network"],
        ))

    return findings


def _run_lighthouse(target: PageTarget) -> list[Finding]:
    """Shell out to the Lighthouse CLI (npx lighthouse) for Core Web Vitals.

    Requires Node.js/npx on PATH (`npm install -g lighthouse`, or let
    npx fetch it on first use).
    """
    findings: list[Finding] = []
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        fallback = Path(os.environ.get("ProgramFiles", r"C:\\Program Files")) / "npx.cmd"
        npx = str(fallback) if fallback.exists() else None
    if not npx:
        return [Finding(
            url=target.url, agent=AgentSource.A11Y_PERF, severity=Severity.LOW,
            title="Lighthouse run failed", detail="npx was not found on PATH.",
            tags=["perf", "scan-error"],
        )]

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out_path = tmp.name

    try:
        subprocess.run(
            [
                npx, "--yes", "lighthouse", target.url,
                "--output=json", f"--output-path={out_path}",
                "--chrome-flags=--headless --no-sandbox",
                "--only-categories=performance,accessibility",
                "--quiet",
            ],
            check=True, timeout=120, capture_output=True,
        )
        with open(out_path) as f:
            report = json.load(f)
    except Exception as e:
        return [Finding(
            url=target.url, agent=AgentSource.A11Y_PERF, severity=Severity.LOW,
            title="Lighthouse run failed", detail=str(e), tags=["perf", "scan-error"],
        )]

    audits = report.get("audits", {})
    for metric_id, threshold in CWV_THRESHOLDS.items():
        audit = audits.get(metric_id)
        if not audit:
            continue
        value = audit.get("numericValue")
        if value is None:
            continue
        is_bad = value > threshold["good_ms"]
        if is_bad:
            findings.append(Finding(
                url=target.url, agent=AgentSource.A11Y_PERF, severity=Severity.MEDIUM,
                title=f"{threshold['label']} exceeds 'good' threshold",
                detail=f"{threshold['label']} = {value} (threshold: {threshold['good_ms']})",
                tags=["perf", "core-web-vitals", metric_id],
            ))

    return findings
