"""Stage 3 — Core Web Vitals (LCP / CLS / INP).

Primary path: Lighthouse CLI (`lighthouse --output=json`), which is what
ships in the container. If the binary is unavailable (bare local dev box),
we fall back to an in-page PerformanceObserver lab measurement so the
stage still produces honest, clearly-labelled numbers instead of nothing.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from playwright.async_api import Browser

from .. import config
from ..models import Finding, finding_id
from ..ratelimit import RateLimiter
from .browser import goto_polite, new_context

_OBSERVER_JS = """() => {
  window.__cwv = {lcp: 0, cls: 0, inp: 0, fcp: 0};
  try {
    new PerformanceObserver(l => {
      for (const e of l.getEntries()) window.__cwv.lcp = Math.max(window.__cwv.lcp, e.startTime);
    }).observe({type: 'largest-contentful-paint', buffered: true});
    new PerformanceObserver(l => {
      for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cwv.cls += e.value;
    }).observe({type: 'layout-shift', buffered: true});
    new PerformanceObserver(l => {
      for (const e of l.getEntries()) window.__cwv.inp = Math.max(window.__cwv.inp, e.duration);
    }).observe({type: 'event', buffered: true, durationThreshold: 40});
    new PerformanceObserver(l => {
      for (const e of l.getEntries()) if (e.name === 'first-contentful-paint') window.__cwv.fcp = e.startTime;
    }).observe({type: 'paint', buffered: true});
  } catch (e) {}
}"""


def _lighthouse_binary() -> list[str] | None:
    exe = shutil.which("lighthouse")
    if exe:
        return [exe]
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx:
        return [npx, "--yes", "lighthouse"]
    return None


def _chromium_path() -> str | None:
    """Locate the Chromium binary Playwright installed, so Lighthouse can
    drive it. Handles both the Linux (container) and Windows (dev) layouts."""
    roots: list[Path] = []
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        roots.append(Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]))
    roots += [
        Path.home() / "AppData/Local/ms-playwright",
        Path.home() / ".cache/ms-playwright",
    ]
    patterns = (
        "chromium-*/chrome-linux/chrome",
        "chromium-*/chrome-win/chrome.exe",
        "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
    )
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in patterns:
            for candidate in sorted(root.glob(pattern), reverse=True):
                if candidate.is_file():
                    return str(candidate)
    return None


async def _run_lighthouse(url: str, log) -> dict[str, Any] | None:
    binary = _lighthouse_binary()
    if not binary:
        log("lighthouse CLI not found — using in-page PerformanceObserver fallback")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "lh.json"
        cmd = [
            *binary, url,
            "--quiet", "--output=json", f"--output-path={out}",
            "--only-categories=performance",
            "--form-factor=mobile",
            "--screenEmulation.mobile=true",
            "--chrome-flags=--headless=new --no-sandbox --disable-dev-shm-usage",
        ]
        chrome = _chromium_path()
        env = dict(os.environ)
        if chrome:
            env["CHROME_PATH"] = chrome
        log("running Lighthouse CLI (mobile form factor, performance category)")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, env=env
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=config.VITALS_BUDGET)
        except asyncio.TimeoutError:
            proc.kill()
            log(f"lighthouse timed out after {config.VITALS_BUDGET:.0f}s — falling back")
            return None
        if proc.returncode != 0 or not out.is_file():
            log(f"lighthouse failed (exit {proc.returncode}) — falling back")
            return None
        data = json.loads(out.read_text(encoding="utf-8"))

    audits = data.get("audits", {})

    def metric(key: str) -> float | None:
        value = audits.get(key, {}).get("numericValue")
        return float(value) if isinstance(value, (int, float)) else None

    return {
        "source": "lighthouse-cli",
        "performance_score": round((data.get("categories", {}).get("performance", {})
                                    .get("score") or 0) * 100),
        "lcp_ms": metric("largest-contentful-paint"),
        "cls": metric("cumulative-layout-shift"),
        "tbt_ms": metric("total-blocking-time"),
        "fcp_ms": metric("first-contentful-paint"),
        "speed_index_ms": metric("speed-index"),
        "inp_ms": None,
        "inp_note": "Lighthouse lab runs cannot measure INP; TBT is reported as the lab proxy.",
    }


async def _run_observer(browser: Browser, url: str, limiter: RateLimiter, log) -> dict[str, Any]:
    context = await new_context(browser, config.VIEWPORTS["mobile"])
    try:
        page = await context.new_page()
        await page.add_init_script(_OBSERVER_JS)
        await goto_polite(page, url, limiter)
        await page.wait_for_timeout(2500)
        # A couple of real interactions so event-timing has something to report.
        await page.keyboard.press("Tab")
        await page.mouse.move(40, 40)
        await page.wait_for_timeout(600)
        raw = await page.evaluate("() => window.__cwv || {}")
    finally:
        await context.close()
    log("in-page CWV observer completed (lab estimate, single run)")
    return {
        "source": "playwright-observer",
        "performance_score": None,
        "lcp_ms": round(raw.get("lcp", 0) or 0) or None,
        "cls": round(raw.get("cls", 0) or 0, 4),
        "inp_ms": round(raw.get("inp", 0) or 0) or None,
        "fcp_ms": round(raw.get("fcp", 0) or 0) or None,
        "tbt_ms": None,
        "inp_note": "INP approximated from event-timing during scripted interaction.",
    }


def _grade(value: float | None, bounds: tuple[float, float]) -> str | None:
    if value is None:
        return None
    good, poor = bounds
    return "critical" if value > poor else ("high" if value > good else None)


async def run(browser: Browser, url: str, limiter: RateLimiter, log) -> tuple[dict[str, Any], list[Finding]]:
    vitals = await _run_lighthouse(url, log)
    if vitals is None:
        vitals = await _run_observer(browser, url, limiter, log)

    findings: list[Finding] = []
    labels = {
        "lcp_ms": ("LCP", "largest-contentful-paint", "ms", 0),
        "cls": ("CLS", "cumulative-layout-shift", "", 4),
        "inp_ms": ("INP", "interaction-to-next-paint", "ms", 0),
        "tbt_ms": ("TBT", "total-blocking-time", "ms", 0),
    }
    for key, (label, full, unit, digits) in labels.items():
        value = vitals.get(key)
        severity = _grade(value, config.CWV_THRESHOLDS[key])
        if severity is None or value is None:
            continue
        shown = f"{value:.{digits}f}{unit}" if unit else f"{value:.{digits}f}"
        findings.append(
            Finding(
                id=finding_id("performance", key),
                category="performance",
                severity=severity,
                title=f"{label} fails Core Web Vitals ({shown})",
                detail=(
                    f"{full} measured at {shown} on a mobile profile "
                    f"(source: {vitals['source']}). Google's 'good' threshold is "
                    f"{config.CWV_THRESHOLDS[key][0]}{unit}."
                ),
                evidence={"metric": key, "value": value, "source": vitals["source"]},
                recommendation=(
                    "Prioritise the LCP element (preload hero media, cut render-blocking CSS), "
                    "reserve space for late-loading blocks to fix CLS, and reduce long tasks to fix INP."
                ),
            )
        )
    log(f"vitals: {json.dumps({k: v for k, v in vitals.items() if k.endswith(('_ms', 'cls', 'score', 'source'))})}")
    return vitals, findings
