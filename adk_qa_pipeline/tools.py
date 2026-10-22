"""Execution layer: deterministic QA checks wrapped as ADK-callable tools.

Every function here is a plain Python function with type hints and a rich
docstring - Google ADK auto-wraps these as FunctionTools when passed into an
Agent's tools=[] list.

Safety invariants preserved from the procedural codebase (src/xoxoday_qa/):
  - robots.txt gate, fail-closed, before every navigation
  - honest, contactable User-Agent on every request
  - 1.5s minimum delay between page loads (single polite visitor, never a load test)
  - forms are filled and inspected but NEVER submitted

These helpers delegate to the original modules rather than reimplementing
them, so a fix in src/xoxoday_qa benefits both pipelines.
"""

from __future__ import annotations

import contextvars
import json
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_REPO_ROOT / "src"), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from xoxoday_qa.config import RUN, SAFETY  # noqa: E402
from xoxoday_qa.crawler import check_robots_allowed  # noqa: E402
from xoxoday_qa.playwright_utils import (  # noqa: E402
    chromium_path,
    PageMonitor,
    browser_session,
    goto_and_settle,
    new_context,
    screenshot_at_breakpoints,
    throttle,
)

# --- Bridge plumbing -------------------------------------------------------
# When the product engine (app/adk_engine.py) drives a scan it points
# _RUN_DIR at runs/<scan_id>/ so raw tool artifacts live with the job and
# get swept by the same TTL. Standalone `adk web` runs fall back to
# ARTIFACTS_DIR.
_RUN_DIR: contextvars.ContextVar["Path | None"] = contextvars.ContextVar(
    "adk_run_dir", default=None
)


def set_run_dir(path: "Path | None") -> None:
    _RUN_DIR.set(path)


def _artifacts_dir() -> Path:
    run_dir = _RUN_DIR.get()
    return (run_dir / "adk_raw") if run_dir else ARTIFACTS_DIR


def _stash(tool_context: Any, tool_name: str, payload: dict[str, Any]) -> None:
    """Stash the FULL payload in ADK session state so the report layer builds
    findings deterministically, while the model only sees the compact summary
    returned by the wrapper (this is what keeps per-scan token cost low)."""
    if tool_context is None:
        return
    try:
        tool_context.state[f"raw:{tool_name}"] = payload
    except Exception:
        pass  # state is a best-effort channel; the artifact file is the backup


AXE_CORE_CDN = "https://unpkg.com/axe-core@4.10.0/axe.min.js"
AXE_CORE_LOCAL_PATH = _REPO_ROOT / "node_modules" / "axe-core" / "axe.min.js"
ARTIFACTS_DIR = _REPO_ROOT / "local_findings_adk"

CWV_THRESHOLDS = {
    "largest-contentful-paint": {"good_ms": 2500, "label": "LCP"},
    "cumulative-layout-shift": {"good_ms": 0.1, "label": "CLS"},
    "interaction-to-next-paint": {"good_ms": 200, "label": "INP"},
}

_IMPACT_MAP = {
    "critical": "critical",
    "serious": "high",
    "moderate": "medium",
    "minor": "low",
}

BOUNDARY_TEST_CASES = [
    {"label": "min employee count", "field_hint": "employee", "value": "1"},
    {"label": "very large employee count", "field_hint": "employee", "value": "100000"},
    {"label": "JPY-style zero-decimal reward amount", "field_hint": "amount", "value": "50000"},
    {"label": "two-decimal reward amount", "field_hint": "amount", "value": "49.99"},
    {"label": "non-Latin name", "field_hint": "name", "value": "田中 太郎"},
    {"label": "name with diacritics", "field_hint": "name", "value": "François Müller"},
    {"label": "international phone format", "field_hint": "phone", "value": "+91 98765 43210"},
    {"label": "invalid email, no @", "field_hint": "email", "value": "not-an-email"},
]

OVERFLOW_PROBE_JS = """
() => {
  const de = document.documentElement;
  const overflowPx = Math.max(de.scrollWidth - window.innerWidth, 0);
  let overflowingElements = 0;
  const limit = de.querySelectorAll('*').length;
  for (const el of de.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.right > window.innerWidth + 8 && r.width > 24) overflowingElements += 1;
    if (overflowingElements >= 25) break;
  }
  return { viewportWidth: window.innerWidth, scrollWidth: de.scrollWidth,
           overflowPx, overflowingElements };
}
"""


def page_slug(url: str) -> str:
    """Filesystem-safe slug mirroring screenshot naming conventions."""
    return url.rstrip("/").split("/")[-1] or "home"


BUYER_QUESTIONS_BY_DOMAIN: dict[str, list[str]] = {
    "xoxoday": [
        "What does Xoxoday's {product} product do?",
        "Does Xoxoday support WhatsApp reward delivery?",
        "What countries can Xoxoday deliver rewards to?",
        "Does Xoxoday have an AI assistant or AI-personalized recommendations?",
    ],
}

DEFAULT_BUYER_QUESTIONS = [
    "What does this company's core product do?",
    "What integrations or platforms does it support (e.g. messaging apps like WhatsApp, Slack)?",
    "What countries or regions does it serve?",
    "Does it offer AI features or AI-assisted functionality?",
    "How is the product priced?",
    "What support channels are available?",
]


def get_buyer_questions(url: str) -> list[str]:
    """Per-domain buyer questions for the GEO/AEO hallucination check.

    Add a domain key here to customize questions for a new target;
    unknown domains get the generic B2B set.
    """
    lowered = url.lower()
    for domain_key, questions in BUYER_QUESTIONS_BY_DOMAIN.items():
        if domain_key in lowered:
            product = "Plum" if "plum" in lowered else (
                "Empuls" if "empuls" in lowered else (
                    "Compass" if "compass" in lowered else "flagship"))
            return [q.format(product=product) for q in questions]
    return list(DEFAULT_BUYER_QUESTIONS)



def _gate(url: str) -> dict[str, Any] | None:
    """Fail-closed robots.txt gate shared by every tool."""
    ua = SAFETY.resolved_user_agent()
    try:
        rp = check_robots_allowed(url, ua)
        if not rp.can_fetch(ua, url):
            return {
                "status": "blocked",
                "reason": f"robots.txt disallows fetching {url} for this agent; "
                          "policy is fail-closed, aborting.",
            }
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": f"robots.txt could not be verified ({exc}); policy is "
                      "fail-closed, aborting.",
        }
    return None


def _record(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist each tool result as a JSON artifact so aggregation never
    depends on the LLM faithfully repeating tool output."""
    out_dir = _artifacts_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(payload.get("url", "")))[
        :60
    ].strip("_")
    out = out_dir / f"{tool_name}_{slug}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    payload["artifact"] = str(out)
    return payload


def _run_axe_core_audit_sync(url: str) -> dict[str, Any]:
    """Run a WCAG 2.2 A/AA accessibility audit of `url` using axe-core.

    Injects the locally bundled axe.min.js into a headless Chromium page
    (falls back to the CDN copy only if the local bundle is missing), runs
    the wcag2a / wcag2aa / wcag22aa rule tags, and additionally reports
    silent failures observed during load (JS console errors, HTTP >=400
    responses, and 200-OK-with-error-payload API responses).

    Args:
        url: Fully-qualified page URL to audit.

    Returns:
        Dict with status, the target url, a findings list (severity-mapped
        axe violations plus silent failures), and a violation count.
    """
    blocked = _gate(url)
    if blocked:
        return {**blocked, "tool": "run_axe_core_audit", "url": url}

    monitor = PageMonitor()
    findings: list[dict[str, Any]] = []
    try:
        with browser_session() as browser:
            ctx = new_context(browser, {"width": 1440, "height": 900})
            page = ctx.new_page()
            monitor.attach(page)

            throttle()
            goto_and_settle(page, url)

            if AXE_CORE_LOCAL_PATH.exists():
                page.add_script_tag(path=str(AXE_CORE_LOCAL_PATH))
            else:
                page.add_script_tag(url=AXE_CORE_CDN)

            results_json = page.evaluate(
                """
                async () => {
                    const results = await axe.run(document, {
                        runOnly: { type: 'tag',
                                   values: ['wcag2a', 'wcag2aa', 'wcag22aa'] }
                    });
                    return JSON.stringify(results.violations);
                }
                """
            )
            violations = json.loads(results_json)
            ctx.close()

        for v in violations:
            findings.append({
                "severity": _IMPACT_MAP.get(v.get("impact"), "medium"),
                "title": f"A11y: {v.get('id')} — {v.get('help')}",
                "detail": (
                    f"{v.get('description', '')} Affects "
                    f"{len(v.get('nodes', []))} element(s). {v.get('helpUrl', '')}"
                ),
                "tags": ["a11y", "wcag", v.get("id", "")],
                "affected_selectors": [
                    n.get("target") for n in v.get("nodes", [])
                ][:5],
            })

        for err in monitor.console_errors[:20]:
            findings.append({
                "severity": "medium",
                "title": "JS console error (no visible break)",
                "detail": err,
                "tags": ["silent-failure", "console-error"],
            })
        for failure in monitor.network_failures[:20]:
            kind = failure.get("kind")
            findings.append({
                "severity": "high" if kind == "silent_error_payload" else "medium",
                "title": f"Silent network failure: {kind}",
                "detail": f"{failure.get('url')} (status={failure.get('status')})",
                "tags": ["silent-failure", kind or "network"],
            })

        return _record("run_axe_core_audit", {
            "status": "ok",
            "tool": "run_axe_core_audit",
            "url": url,
            "violation_count": len(findings),
            "findings": findings,
        })
    except Exception as exc:
        return _record("run_axe_core_audit", {
            "status": "error",
            "tool": "run_axe_core_audit",
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "findings": findings,
        })


def _lighthouse_command() -> list[str] | None:
    """Locate the Lighthouse CLI. The container image installs lighthouse@12
    globally, so prefer that binary; npx (which re-resolves the package from
    the npm registry on every cold start) is the last resort."""
    exe = shutil.which("lighthouse")
    if exe:
        return [exe]
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        progfiles = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "npx.cmd"
        if progfiles.exists():
            npx = str(progfiles)
    return [npx, "--yes", "lighthouse"] if npx else None


def _run_lighthouse_audit_sync(url: str) -> dict[str, Any]:
    """Measure Core Web Vitals (LCP / CLS / INP) and accessibility score for
    `url` by shelling out to the Lighthouse CLI.

    Requires Node/npx on PATH. Flags any metric worse than Google's
    published 'good' thresholds.

    Args:
        url: Fully-qualified page URL to audit.

    Returns:
        Dict with status, recorded metric values, and a findings list for
        each threshold breach.
    """
    blocked = _gate(url)
    if blocked:
        return {**blocked, "tool": "run_lighthouse_audit", "url": url}

    cmd = _lighthouse_command()
    if not cmd:
        return _record("run_lighthouse_audit", {
            "status": "error",
            "tool": "run_lighthouse_audit",
            "url": url,
            "error": "Lighthouse CLI unavailable: no 'lighthouse' binary or npx found on PATH.",
            "findings": [],
        })

    metrics: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out_path = tmp.name

    chrome_flags = "--headless=new --no-sandbox --disable-dev-shm-usage --disable-gpu"
    chrome = chromium_path()
    env = dict(os.environ)
    if chrome:
        # The container has no system Chrome; point Lighthouse's
        # chrome-launcher at the Chromium Playwright installed.
        env["CHROME_PATH"] = chrome
    report = None
    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            subprocess.run(
                [
                    *cmd, url,
                    "--output=json", f"--output-path={out_path}",
                    f"--chrome-flags={chrome_flags}",
                    "--only-categories=performance,accessibility",
                    "--quiet",
                ],
                check=True, timeout=240, capture_output=True, text=True, env=env,
            )
        except Exception as exc:
            last_exc = exc
            # Lighthouse frequently exits non-zero on hostile targets yet
            # still writes a usable report - salvage it if present.
            if Path(out_path).exists() and Path(out_path).stat().st_size > 100:
                break
            continue
        break
    try:
        if Path(out_path).exists() and Path(out_path).stat().st_size > 100:
            with open(out_path) as f:
                report = json.load(f)
    except Exception as exc:
        last_exc = exc
        report = None
    if report is None:
        if last_exc is not None and getattr(last_exc, "stderr", None):
            detail = "Lighthouse CLI exited without a report | stderr: " + str(last_exc.stderr)[-300:]
        elif last_exc is not None:
            detail = f"Lighthouse CLI exited without a report ({type(last_exc).__name__})"
        else:
            detail = "Lighthouse CLI produced no report"
        return _record("run_lighthouse_audit", {
            "status": "error",
            "tool": "run_lighthouse_audit",
            "url": url,
            "error": detail,
            "findings": [],
        })

    audits = report.get("audits", {})
    for metric_id, threshold in CWV_THRESHOLDS.items():
        audit = audits.get(metric_id) or {}
        value = audit.get("numericValue")
        if value is None:
            continue
        metrics[threshold["label"]] = value
        if value > threshold["good_ms"]:
            findings.append({
                "severity": "medium",
                "title": f"{threshold['label']} exceeds 'good' threshold",
                "detail": f"{threshold['label']} = {value} (threshold: {threshold['good_ms']})",
                "tags": ["perf", "core-web-vitals", metric_id],
            })

    cats = report.get("categories", {})
    scores = {
        cat: (cats.get(cat, {}) or {}).get("score")
        for cat in ("performance", "accessibility")
    }

    return _record("run_lighthouse_audit", {
        "status": "ok",
        "tool": "run_lighthouse_audit",
        "url": url,
        "metrics": metrics,
        "scores": scores,
        "findings": findings,
    })


def _fetch_page_text_snapshot_sync(url: str) -> dict[str, Any]:
    """Extract the textual ground truth of `url` for factual-consistency work.

    Returns the meta description, a summary of any JSON-LD structured-data
    blocks (types + parsed-or-malformed status), and the first ~4000
    characters of visible body text. The GEO/AEO agent diffs its own answers
    to buyer questions against this snapshot to detect hallucinations.

    Args:
        url: Fully-qualified page URL to read.

    Returns:
        Dict with meta_description, jsonld_blocks, and body_text_excerpt.
    """
    blocked = _gate(url)
    if blocked:
        return {**blocked, "tool": "fetch_page_text_snapshot", "url": url}

    try:
        with browser_session() as browser:
            ctx = new_context(browser, {"width": 1440, "height": 900})
            page = ctx.new_page()
            throttle()
            goto_and_settle(page, url)

            try:
                meta_desc = page.locator(
                    'meta[name="description"]'
                ).first.get_attribute("content", timeout=5_000) or ""
            except Exception:
                meta_desc = ""

            jsonld_blocks: list[dict[str, Any]] = []
            blocks = page.locator('script[type="application/ld+json"]')
            for i in range(min(blocks.count(), 10)):
                raw = blocks.nth(i).inner_text()
                entry: dict[str, Any] = {"index": i, "valid_json": True}
                try:
                    data = json.loads(raw)
                    types_ = data.get("@type") if isinstance(data, dict) else None
                    entry["@type"] = types_
                except json.JSONDecodeError:
                    entry["valid_json"] = False
                jsonld_blocks.append(entry)

            body_text = page.locator("body").inner_text(timeout=5_000)
            ctx.close()

        return _record("fetch_page_text_snapshot", {
            "status": "ok",
            "tool": "fetch_page_text_snapshot",
            "url": url,
            "meta_description": meta_desc.strip(),
            "jsonld_blocks": jsonld_blocks,
            "body_text_excerpt": body_text[:4000],
        })
    except Exception as exc:
        return _record("fetch_page_text_snapshot", {
            "status": "error",
            "tool": "fetch_page_text_snapshot",
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
        })


def _capture_viewport_screenshots_sync(url: str) -> dict[str, Any]:
    """Capture full-page headless screenshots of `url` at mobile (390px),
    tablet (834px), and desktop (1440px) breakpoints.

    At each breakpoint it also runs a deterministic horizontal-overflow probe
    (scrollWidth vs viewport width, count of elements spilling past the right
    edge) so the calling agent gets machine-readable layout signal in addition
    to the saved PNGs.

    Args:
        url: Fully-qualified page URL to capture.

    Returns:
        Dict mapping each breakpoint to its screenshot path plus overflow
        stats, suitable for downstream vision review or report embedding.
    """
    blocked = _gate(url)
    if blocked:
        return {**blocked, "tool": "capture_viewport_screenshots", "url": url}

    out_dir = str(_REPO_ROOT / RUN.screenshots_dir)
    results: dict[str, Any] = {}
    try:
        with browser_session() as browser:
            paths = screenshot_at_breakpoints(browser, url, out_dir)
            for name, viewport in RUN.viewports.items():
                probe: dict[str, Any] = {}
                try:
                    ctx = new_context(browser, viewport)
                    page = ctx.new_page()
                    throttle()
                    goto_and_settle(page, url)
                    probe = page.evaluate(OVERFLOW_PROBE_JS)
                    ctx.close()
                except Exception as exc:
                    probe = {"probe_error": f"{type(exc).__name__}: {exc}"}
                results[name] = {"screenshot": paths.get(name), **probe}
    except Exception as exc:
        return _record("capture_viewport_screenshots", {
            "status": "error",
            "tool": "capture_viewport_screenshots",
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "breakpoints": {},
        })

    findings = [
        {
            "severity": "high" if r.get("overflowPx", 0) > 16 else "medium",
            "title": f"[{name}] horizontal overflow detected",
            "detail": (
                f"scrollWidth={r.get('scrollWidth')} exceeds viewport "
                f"{r.get('viewportWidth')} by {r.get('overflowPx')}px; "
                f"{r.get('overflowingElements')} elements spill past the edge."
            ),
            "evidence_uri": r.get("screenshot"),
            "tags": ["visual", name, "overflow"],
        }
        for name, r in results.items()
        if r.get("overflowPx", 0) > 0
    ]

    return _record("capture_viewport_screenshots", {
        "status": "ok",
        "tool": "capture_viewport_screenshots",
        "url": url,
        "breakpoints": results,
        "findings": findings,
    })


def _test_form_boundaries_sync(url: str, selector: str = "form") -> dict[str, Any]:
    """Probe the validation behaviour of a form at `url` with boundary values.

    Fills visible inputs (matched by name/id/placeholder hints for employee
    count, amount, name, phone, email) with internationalized and edge-case
    values, triggers blur-based validation, and reads back aria-invalid state
    plus nearby error messaging.

    HARD SAFETY RULE: fields are filled and inspected only. The submit button
    is never located, never focused, never clicked. Test data is tagged with
    the project's dummy-data marker so any stray autosave beacon is visibly
    synthetic.

    Args:
        url: Fully-qualified page URL containing the form.
        selector: CSS selector resolving to the form under test
            (defaults to the first <form> on the page).

    Returns:
        Dict with per-case validation verdicts and any false-positive /
        missing-validation findings.
    """
    blocked = _gate(url)
    if blocked:
        return {**blocked, "tool": "test_form_boundaries", "url": url}

    findings: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    try:
        with browser_session() as browser:
            ctx = new_context(browser, {"width": 1440, "height": 900})
            page = ctx.new_page()
            throttle()
            goto_and_settle(page, url)

            form = page.locator(selector).first
            if form.count() == 0:
                ctx.close()
                return _record("test_form_boundaries", {
                    "status": "ok",
                    "tool": "test_form_boundaries",
                    "url": url,
                    "case_results": [],
                    "findings": [{
                        "severity": "info",
                        "title": f"No element matches selector '{selector}'",
                        "detail": "Nothing to test.",
                        "tags": ["forms", "pass"],
                    }],
                })

            for case in BOUNDARY_TEST_CASES:
                field = _find_field(form, case["field_hint"])
                if field is None:
                    continue

                value = case["value"]
                if case["field_hint"] == "name":
                    value = f"{SAFETY.dummy_data_marker} ({value})"

                try:
                    field.fill(value)
                    page.keyboard.press("Tab")
                    page.wait_for_timeout(300)
                except Exception as exc:
                    case_results.append({
                        "case": case["label"], "status": "interaction-error",
                        "error": str(exc)[:300],
                    })
                    continue

                aria_invalid = field.get_attribute("aria-invalid")
                invalid_case = (
                    case["field_hint"] == "email"
                    and case["value"] == "not-an-email"
                )

                result = {
                    "case": case["label"],
                    "value_entered": value,
                    "aria_invalid": aria_invalid,
                    "status": "ok",
                }
                case_results.append(result)

                if invalid_case and aria_invalid != "true":
                    findings.append({
                        "severity": "medium",
                        "title": "Invalid email accepted without validation flag",
                        "detail": (
                            "Field did not set aria-invalid=true after entering "
                            f"'{case['value']}'."
                        ),
                        "tags": ["forms", "validation", "a11y-adjacent"],
                    })
                elif not invalid_case and aria_invalid == "true":
                    findings.append({
                        "severity": "medium",
                        "title": f"Valid input flagged as invalid: {case['label']}",
                        "detail": (
                            "Field set aria-invalid=true after entering legitimate "
                            f"value '{case['value']}'."
                        ),
                        "tags": ["forms", "validation", "false-positive"],
                    })

            findings.append({
                "severity": "info",
                "title": "Submit skipped (hard safety policy)",
                "detail": (
                    "Fields were exercised to read validation state; the submit "
                    "control was never clicked, per production-safety policy."
                ),
                "tags": ["forms", "safety", "no-submit"],
            })
            ctx.close()

        return _record("test_form_boundaries", {
            "status": "ok",
            "tool": "test_form_boundaries",
            "url": url,
            "selector": selector,
            "case_results": case_results,
            "findings": findings,
        })
    except Exception as exc:
        return _record("test_form_boundaries", {
            "status": "error",
            "tool": "test_form_boundaries",
            "url": url,
            "selector": selector,
            "error": f"{type(exc).__name__}: {exc}",
            "findings": [],
        })


def _find_field(form: Any, field_hint: str) -> Any | None:
    locator = form.locator(
        f"input[name*='{field_hint}' i], input[id*='{field_hint}' i], "
        f"input[placeholder*='{field_hint}' i]"
    )
    for i in range(locator.count()):
        candidate = locator.nth(i)
        try:
            if candidate.is_visible():
                return candidate
        except Exception:
            continue
    return None

async def run_axe_core_audit(url: str, tool_context: Any = None) -> dict[str, Any]:
    """Run a WCAG 2.2 A/AA axe-core audit of `url` in headless Chromium.

    Also reports silent failures seen during load: JS console errors,
    HTTP >=400 responses, and 200-OK-with-error-payload API responses.
    The full violation list is stashed to session state / artifact JSON;
    this returns a compact summary (counts + top titles) to save tokens.
    Args:
        url: Fully-qualified page URL to audit.
    Returns:
        {status, url, violation_count, top_findings[], artifact}.
    """
    payload = await asyncio.to_thread(_run_axe_core_audit_sync, url)
    _stash(tool_context, "run_axe_core_audit", payload)
    findings = payload.get("findings", [])
    return {
        "status": payload.get("status"),
        "url": url,
        "violation_count": payload.get("violation_count", len(findings)),
        "top_findings": [f"{f.get('severity')}: {f.get('title')}" for f in findings[:5]],
        "artifact": payload.get("artifact"),
        "error": payload.get("error"),
        "reason": payload.get("reason"),
    }


async def run_lighthouse_audit(url: str, tool_context: Any = None) -> dict[str, Any]:
    """Measure Core Web Vitals (LCP/CLS/INP) and perf/a11y scores for `url`
    via the Lighthouse CLI.

    Flags metrics worse than Google's 'good' thresholds. Full payload is
    stashed; this returns a compact summary.
    Args:
        url: Fully-qualified page URL to audit.
    Returns:
        {status, url, metrics{}, scores{}, finding_count, top_findings[]}.
    """
    payload = await asyncio.to_thread(_run_lighthouse_audit_sync, url)
    _stash(tool_context, "run_lighthouse_audit", payload)
    findings = payload.get("findings", [])
    return {
        "status": payload.get("status"),
        "url": url,
        "metrics": payload.get("metrics", {}),
        "scores": payload.get("scores", {}),
        "finding_count": len(findings),
        "top_findings": [f.get("title") for f in findings[:5]],
        "error": payload.get("error"),
        "reason": payload.get("reason"),
    }


async def fetch_page_text_snapshot(url: str, tool_context: Any = None) -> dict[str, Any]:
    """Extract textual ground truth of `url`: meta description, JSON-LD
    block summary, and first ~4000 chars of visible body text.

    Used as the fact base for hallucination/consistency checks, so the
    excerpt is returned in full to the model (it is the reasoning input).
    Args:
        url: Fully-qualified page URL to read.
    Returns:
        {status, url, meta_description, jsonld_blocks[], body_text_excerpt}.
    """
    payload = await asyncio.to_thread(_fetch_page_text_snapshot_sync, url)
    _stash(tool_context, "fetch_page_text_snapshot", payload)
    return payload


async def capture_viewport_screenshots(url: str, tool_context: Any = None) -> dict[str, Any]:
    """Capture full-page screenshots of `url` at mobile/tablet/desktop
    widths plus a deterministic horizontal-overflow probe per breakpoint.

    Args:
        url: Fully-qualified page URL to capture.
    Returns:
        {status, url, breakpoints{name:{screenshot,overflowPx,...}}, finding_count}.
    """
    payload = await asyncio.to_thread(_capture_viewport_screenshots_sync, url)
    _stash(tool_context, "capture_viewport_screenshots", payload)
    return {
        "status": payload.get("status"),
        "url": url,
        "breakpoints": payload.get("breakpoints", {}),
        "finding_count": len(payload.get("findings", [])),
        "error": payload.get("error"),
        "reason": payload.get("reason"),
    }


async def test_form_boundaries(url: str, selector: str = "form", tool_context: Any = None) -> dict[str, Any]:
    """Fill visible inputs of the form at `url` with internationalized
    boundary values and read aria-invalid validation state.

    NEVER clicks submit; data is tagged with the dummy-data marker.
    Args:
        url: Fully-qualified page URL containing the form.
        selector: CSS selector for the form under test (default 'form').
    Returns:
        {status, url, selector, case_results[], findings[]}.
    """
    payload = await asyncio.to_thread(_test_form_boundaries_sync, url, selector)
    _stash(tool_context, "test_form_boundaries", payload)
    return payload
