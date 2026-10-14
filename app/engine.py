"""The orchestrator: runs every stage in order, emits live progress, and
assembles the structured JSON + PDF that the report is built from.

Design notes
  * One Playwright browser per scan, one polite RateLimiter for the origin.
  * Every stage is independently guarded: a failing stage is recorded as
    failed/degraded and the scan continues, because a partial honest
    report beats a hard error.
  * All findings pass through dedup_findings(), so repeat scans are
    reproducible rather than noisy.
  * Stage events carry a running finding count, which is what lets the UI
    show live activity instead of a dumb spinner.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from playwright.async_api import async_playwright

from . import config, report, synthesis
from .models import (
    Finding,
    ScanResult,
    ScreenshotMeta,
    StageResult,
    dedup_findings,
    severity_counts,
)
from .ratelimit import RateLimiter
from .robots import RobotsDenied, check_allowed
from .stages import accessibility, forms, geo_aeo, screenshots, vitals

LogFn = Callable[[str], None]

STAGE_LABELS = [
    ("screenshots", "Capturing screenshots"),
    ("accessibility", "Accessibility audit (WCAG 2.2 A/AA)"),
    ("vitals", "Core Web Vitals (LCP / CLS / INP)"),
    ("forms", "Form safety & validation check"),
    ("ai", "AI-answer check (GEO/AEO)"),
]
STAGE_KEYS = [key for key, _ in STAGE_LABELS]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


async def run_scan(scan_id: str, url: str, run_dir: Path, emit: Callable[[dict], None]) -> ScanResult:
    """Execute a full scan. `emit` receives JSON-serializable event dicts."""

    def log(message: str) -> None:
        emit({"type": "log", "message": message, "ts": time.time()})

    started = time.monotonic()
    run_dir.mkdir(parents=True, exist_ok=True)
    limiter = RateLimiter()
    findings: list[Finding] = []
    shots: list[ScreenshotMeta] = []
    vitals_data: dict[str, Any] = {}
    stage_results: list[StageResult] = []
    final_url = url
    live_total = 0          # findings reported to the UI so far

    def announce(key: str, label: str, status: str, elapsed: float,
                 detail: str = "", found: list[Finding] | None = None,
                 extra: dict[str, Any] | None = None) -> None:
        """Emit a stage event. `findings` is the count this stage produced;
        `live_total` is the running total the UI ticks up."""
        nonlocal live_total
        count = len(found or [])
        live_total += count
        payload: dict[str, Any] = {
            "type": "stage",
            "key": key,
            "label": label,
            "status": status,
            "elapsed_seconds": round(elapsed, 1),
            "detail": detail,
            "findings": count,
            "findings_total": live_total,
        }
        if extra:
            payload.update(extra)
        emit(payload)

    # ---- pre-flight: robots.txt (fail-closed) --------------------------
    emit({"type": "preflight", "message": "Checking robots.txt (fail-closed policy)"})
    verdict = await check_allowed(url, limiter)
    log(f"robots.txt OK — {verdict.reason}")
    emit({"type": "robots", "ok": True, "reason": verdict.reason, "robots_url": verdict.robots_url})

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        try:
            # ---- stage 1: screenshots ----------------------------------
            key, label = STAGE_LABELS[0]
            emit({"type": "stage", "key": key, "label": label, "status": "running"})
            found: list[Finding] = []
            t0 = time.monotonic()
            try:
                found, shots, final_url = await asyncio.wait_for(
                    screenshots.run(browser, url, run_dir, limiter, log), timeout=180
                )
                findings += found
                status, detail = "ok", f"{len(shots)} viewports captured"
            except Exception as exc:  # noqa: BLE001
                status, detail = "failed", f"{type(exc).__name__}: {exc}"
                log(f"screenshots stage failed: {exc}")
            elapsed = time.monotonic() - t0
            stage_results.append(StageResult(key=key, label=label, status=status,
                                             elapsed_seconds=round(elapsed, 1), detail=detail))
            announce(key, label, status, elapsed, detail, found,
                     extra={"viewports": [s.viewport for s in shots],
                            "preview": shots[0].thumb if shots else None})

            # ---- stage 2: accessibility --------------------------------
            key, label = STAGE_LABELS[1]
            emit({"type": "stage", "key": key, "label": label, "status": "running"})
            found = []
            t0 = time.monotonic()
            try:
                found = await asyncio.wait_for(
                    accessibility.run(browser, url, limiter, log), timeout=config.AXE_BUDGET
                )
                findings += found
                status, detail = "ok", f"{len(found)} rule violations"
            except Exception as exc:  # noqa: BLE001
                status, detail = "failed", f"{type(exc).__name__}: {exc}"
                log(f"accessibility stage failed: {exc}")
            elapsed = time.monotonic() - t0
            stage_results.append(StageResult(key=key, label=label, status=status,
                                             elapsed_seconds=round(elapsed, 1), detail=detail))
            announce(key, label, status, elapsed, detail, found)

            # ---- stage 3: core web vitals ------------------------------
            key, label = STAGE_LABELS[2]
            emit({"type": "stage", "key": key, "label": label, "status": "running"})
            found = []
            t0 = time.monotonic()
            try:
                vitals_data, found = await asyncio.wait_for(
                    vitals.run(browser, url, limiter, log), timeout=config.VITALS_BUDGET + 60
                )
                findings += found
                status = "ok" if vitals_data.get("source") == "lighthouse-cli" else "degraded"
                detail = f"source: {vitals_data.get('source')}"
            except Exception as exc:  # noqa: BLE001
                status, detail = "failed", f"{type(exc).__name__}: {exc}"
                log(f"vitals stage failed: {exc}")
            elapsed = time.monotonic() - t0
            stage_results.append(StageResult(key=key, label=label, status=status,
                                             elapsed_seconds=round(elapsed, 1), detail=detail))
            announce(key, label, status, elapsed, detail, found, extra={"vitals": vitals_data})

            # ---- stage 4: forms (never submits) ------------------------
            key, label = STAGE_LABELS[3]
            emit({"type": "stage", "key": key, "label": label, "status": "running"})
            found = []
            t0 = time.monotonic()
            try:
                found = await asyncio.wait_for(
                    forms.run(browser, url, limiter, log), timeout=config.FORMS_BUDGET
                )
                findings += found
                status, detail = "ok", f"{len(found)} validation findings; 0 submissions made"
            except Exception as exc:  # noqa: BLE001
                status, detail = "failed", f"{type(exc).__name__}: {exc}"
                log(f"forms stage failed: {exc}")
            elapsed = time.monotonic() - t0
            stage_results.append(StageResult(key=key, label=label, status=status,
                                             elapsed_seconds=round(elapsed, 1), detail=detail))
            announce(key, label, status, elapsed, detail, found)

            # ---- stage 5: AI answer check + visual review --------------
            key, label = STAGE_LABELS[4]
            emit({"type": "stage", "key": key, "label": label, "status": "running"})
            found = []
            geo_analysis: dict[str, Any] = {}
            t0 = time.monotonic()
            thumb = next((config.REPO_ROOT / s.thumb for s in shots if s.viewport == "desktop"), None)
            try:
                found, geo_analysis = await asyncio.wait_for(
                    geo_aeo.run(browser, url, limiter, log, thumb), timeout=config.AI_BUDGET + 60
                )
                findings += found
                status = "ok" if geo_analysis.get("llm_status") == "ok" else "degraded"
                detail = f"{len(found)} findings; model: {config.GEMINI_MODEL}"
            except Exception as exc:  # noqa: BLE001
                status, detail = "failed", f"{type(exc).__name__}: {exc}"
                log(f"AI stage failed: {exc}")
            elapsed = time.monotonic() - t0
            stage_results.append(StageResult(key=key, label=label, status=status,
                                             elapsed_seconds=round(elapsed, 1), detail=detail))
            announce(key, label, status, elapsed, detail, found,
                     extra={"llm_status": geo_analysis.get("llm_status", "unknown")})
        finally:
            await browser.close()

    # ---- synthesis -----------------------------------------------------
    emit({"type": "log", "message": "deduplicating findings and writing the executive summary"})
    findings = dedup_findings(findings)
    counts = severity_counts(findings)
    synth = await synthesis.synthesize(final_url or url, findings, counts, vitals_data, log)

    result = ScanResult(
        scan_id=scan_id,
        target_url=url,
        final_url=final_url or url,
        scanned_at=_now_iso(),
        elapsed_seconds=round(time.monotonic() - started, 1),
        user_agent=config.USER_AGENT,
        model=config.GEMINI_MODEL,
        severity_counts=counts,
        findings=findings,
        top_risks=synth["top_risks"],
        executive_summary=synth["summary"],
        screenshots=shots,
        vitals=vitals_data,
        stages=stage_results,
        safety={
            "robots_txt": verdict.reason,
            "robots_url": verdict.robots_url,
            "throttle_seconds": config.THROTTLE_SECONDS,
            "user_agent": config.USER_AGENT,
            "forms_submitted": 0,
            "forms_policy": (
                "No submit code path exists. form.submit/requestSubmit are stubbed, a capture-phase "
                "submit listener cancels every submit event, and the network layer aborts all "
                "non-GET requests."
            ),
            "data_submitted": False,
            "ai_model": config.GEMINI_MODEL,
            "ai_model_policy": "Every AI layer runs on gemini-flash-latest only.",
        },
    )

    (run_dir / "report.json").write_text(
        json.dumps(result.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    emit({"type": "log", "message": "structured JSON written — rendering the A4 PDF report"})
    pdf_path = await report.render_pdf(result, run_dir, log)
    result.safety["report_pdf"] = str(pdf_path.relative_to(config.REPO_ROOT))
    (run_dir / "report.json").write_text(
        json.dumps(result.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    emit({"type": "log", "message": f"PDF ready ({pdf_path.name})"})
    return result
