"""ADK engine: the Google ADK agent graph as the scan orchestrator.

Same contract as app.engine.run_scan (scan_id, url, run_dir, emit) -> ScanResult,
but the pipeline is driven by the qa_supervisor_agent LlmAgent routing to four
specialist sub-agents via transfer_to_agent, exactly like the original
adk_qa_pipeline prototype.

Design notes
  * Agents decide what to run; code decides what is true. Findings, severity
    counts, vitals and the PDF are built deterministically from the tools'
    stashed payloads (session state), never from LLM prose.
  * The no-submit guardrail lives in the ADK before_tool_callback
    (prevent_form_submit_guardrail) plus the tool itself never touching a
    submit control — same guarantee as the core engine, enforced in code.
  * Every ADK event is translated into the existing SSE vocabulary, so the
    frontend cannot tell which engine produced the scan.
  * Watchdog: a stalled graph (LLM routing miss, no events) marks the
    affected stages degraded with the honest reason instead of hanging.
  * All agents run on config.GEMINI_MODEL (gemini-flash-latest only).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from . import config, report, synthesis
from .engine import STAGE_LABELS
from .models import (
    Finding,
    ScanResult,
    ScreenshotMeta,
    StageResult,
    dedup_findings,
    finding_id,
    severity_counts,
)
from .ratelimit import RateLimiter
from .robots import check_allowed

# ADK tool name -> product stage key.
TOOL_STAGE = {
    "capture_viewport_screenshots": "screenshots",
    "run_axe_core_audit": "accessibility",
    "run_lighthouse_audit": "vitals",
    "test_form_boundaries": "forms",
    "fetch_page_text_snapshot": "ai",
}

# Specialist agent -> stage it owns (opens the stage as soon as the
# supervisor transfers, so the UI shows intent before the first tool call).
AGENT_STAGE = {
    "visual_qa_agent": "screenshots",
    "a11y_perf_agent": "accessibility",
    "forms_agent": "forms",
    "geo_aeo_agent": "ai",
}

STAGE_LABEL = dict(STAGE_LABELS)
VIEWPORT_ORDER = ["desktop", "tablet", "mobile"]
SEVERITIES = ("critical", "high", "medium", "low", "info")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sev(value: Any, default: str = "medium") -> str:
    return value if value in SEVERITIES else default


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of an agent reply (fence-tolerant)."""
    start = text.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _geo_findings(text: str) -> list[Finding]:
    """Turn the geo_aeo agent's UNSUPPORTED / NOT_MENTIONED classifications
    into deterministic findings."""
    findings: list[Finding] = []
    for line in text.splitlines():
        clean = line.strip().strip("-*•0123456789. ")
        upper = clean.upper()
        if "_DONE" in upper or upper.startswith("HANDING_BACK"):
            continue  # completion markers, not classifications
        if "UNSUPPORTED" in upper:
            title, sev, cls = "AI-answer risk: claim not supported by page content", "high", "UNSUPPORTED"
        elif "NOT_MENTIONED" in upper:
            title, sev, cls = "AI-answer gap: buyer question not answered on page", "medium", "NOT_MENTIONED"
        else:
            continue
        detail = clean[:320]
        findings.append(Finding(
            id=finding_id("geo_aeo", title, detail[:120]),
            category="geo_aeo", severity=sev, title=title, detail=detail,
            evidence={"classification": cls},
            recommendation="Add or clarify on-page copy so answer engines can cite a verifiable source.",
        ))
        if len(findings) >= 12:
            break
    return findings


def _axe_findings(payload: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for f in payload.get("findings", []):
        tags = f.get("tags", [])
        category = "accessibility" if "a11y" in tags else "technical"
        selectors = [str(s) for s in (f.get("affected_selectors") or []) if s][:5]
        title = str(f.get("title", ""))[:160]
        out.append(Finding(
            id=finding_id(category, title, selectors[0] if selectors else ""),
            category=category, severity=_sev(f.get("severity")), title=title,
            detail=str(f.get("detail", ""))[:600],
            evidence={"selector": selectors[0] if selectors else "", "affected": selectors},
        ))
    return out


def _visual_findings(payload: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for f in payload.get("findings", []):
        title = str(f.get("title", ""))[:160]
        out.append(Finding(
            id=finding_id("visual", title),
            category="visual", severity=_sev(f.get("severity")), title=title,
            detail=str(f.get("detail", ""))[:600],
            evidence={"capture": str(f.get("evidence_uri", ""))},
            recommendation="Constrain wide elements to the viewport (max-width:100%, audit overflow-x).",
        ))
    return out


def _forms_findings(payload: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for f in payload.get("findings", []):
        title = str(f.get("title", ""))[:160]
        out.append(Finding(
            id=finding_id("forms", title, str(f.get("detail", ""))[:80]),
            category="forms", severity=_sev(f.get("severity"), "info"), title=title,
            detail=str(f.get("detail", ""))[:600],
            recommendation="Validate on blur and submit; expose state via aria-invalid + inline errors.",
        ))
    return out


def _perf_findings(payload: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for f in payload.get("findings", []):
        title = str(f.get("title", ""))[:160]
        out.append(Finding(
            id=finding_id("performance", title),
            category="performance", severity="medium", title=title,
            detail=str(f.get("detail", ""))[:600],
            recommendation="Bring the metric under Google's 'good' threshold (see web.dev/vitals).",
        ))
    return out


def _vitals_from(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = payload.get("metrics", {})
    scores = payload.get("scores", {})
    perf = scores.get("performance")
    inp = metrics.get("INP")
    return {
        "lcp_ms": metrics.get("LCP"),
        "cls": metrics.get("CLS"),
        "inp_ms": inp,
        "tbt_ms": None,
        "performance_score": round(perf * 100) if isinstance(perf, (int, float)) else None,
        "source": "lighthouse-cli",
        "inp_note": "" if inp is not None else "Lighthouse lab runs cannot measure INP; TBT is the lab proxy.",
    }


def _import_shots(payload: dict[str, Any], run_dir: Path, log) -> list[ScreenshotMeta]:
    """Copy the ADK tool's PNG captures into the job's shots/ dir and mint
    JPEG thumbnails, matching the artifact layout the UI and PDF expect."""
    shots_dir = run_dir / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    metas: list[ScreenshotMeta] = []
    for name in VIEWPORT_ORDER:
        entry = (payload.get("breakpoints", {}) or {}).get(name) or {}
        src = entry.get("screenshot")
        if not src or not Path(src).is_file():
            continue
        png = shots_dir / f"{name}.png"
        shutil.copyfile(src, png)
        thumb = shots_dir / f"{name}.jpg"
        with Image.open(png) as im:
            w, h = im.size
            tw = 1100
            th = max(1, round(h * tw / w))
            im.convert("RGB").resize((tw, th), Image.LANCZOS).save(thumb, "JPEG", quality=80)
        metas.append(ScreenshotMeta(
            viewport=name,
            path=str(png.relative_to(config.REPO_ROOT)),
            thumb=str(thumb.relative_to(config.REPO_ROOT)),
            width=w, height=h,
            overflow_x=bool(entry.get("overflowPx", 0) > 0),
            overflow_px=int(entry.get("overflowPx", 0) or 0),
        ))
    log(f"imported {len(metas)} viewport captures from the visual agent")
    return metas


def _resp_count(tool: str, resp: dict[str, Any]) -> int:
    """Finding count straight from the compact tool response (no LLM prose)."""
    if tool == "run_axe_core_audit":
        return int(resp.get("violation_count") or 0)
    if tool in ("capture_viewport_screenshots", "run_lighthouse_audit"):
        return int(resp.get("finding_count") or 0)
    if tool == "test_form_boundaries":
        return len(resp.get("findings") or [])
    return 0


async def run_scan(scan_id: str, url: str, run_dir: Path, emit: Callable[[dict], None]) -> ScanResult:
    """Execute a full scan orchestrated by the ADK agent graph."""

    def log(message: str) -> None:
        emit({"type": "log", "message": message, "ts": time.time()})

    started = time.monotonic()
    run_dir.mkdir(parents=True, exist_ok=True)

    # ---- pre-flight: robots.txt (fail-closed, product policy) ------------
    emit({"type": "preflight", "message": "Checking robots.txt (fail-closed policy)"})
    verdict = await check_allowed(url, RateLimiter())
    log(f"robots.txt OK — {verdict.reason}")
    emit({"type": "robots", "ok": True, "reason": verdict.reason, "robots_url": verdict.robots_url})

    # ---- ADK setup --------------------------------------------------------
    api_key = config.gemini_api_key()
    if not api_key:
        raise RuntimeError("ADK engine requires GEMINI_API_KEY (the agent graph is LLM-driven).")
    os.environ.setdefault("GOOGLE_API_KEY", api_key)

    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types as genai_types

    from adk_qa_pipeline import agents as adk_agents
    from adk_qa_pipeline import tools as adk_tools

    adk_tools.set_run_dir(run_dir)

    app_name = "sitesentinel_adk"
    user_id = "scanner"
    session_service = InMemorySessionService()
    await session_service.create_session(app_name=app_name, user_id=user_id, session_id=scan_id)
    runner = Runner(agent=adk_agents.qa_supervisor_agent, app_name=app_name, session_service=session_service)
    message = genai_types.Content(role="user", parts=[genai_types.Part(text=f"Audit this target URL: {url}")])

    # ---- live translation: ADK events -> product SSE vocabulary -----------
    stage_status: dict[str, str] = {}
    stage_elapsed: dict[str, float] = {}
    stage_counts: dict[str, int] = {}
    stage_start: dict[str, float] = {}
    early_shots: list["ScreenshotMeta"] = []
    live_total = 0
    supervisor_text: list[str] = []
    geo_text: list[str] = []

    def stage_begin(key: str) -> None:
        if key in stage_status:
            return
        stage_status[key] = "running"
        stage_start[key] = time.monotonic()
        emit({"type": "stage", "key": key, "label": STAGE_LABEL[key], "status": "running"})

    def stage_end(key: str, status: str, detail: str, found: int = 0) -> None:
        nonlocal live_total
        live_total += found
        stage_status[key] = status
        stage_counts[key] = stage_counts.get(key, 0) + found
        stage_elapsed[key] = round(time.monotonic() - stage_start.get(key, started), 1)
        emit({
            "type": "stage", "key": key, "label": STAGE_LABEL[key], "status": status,
            "elapsed_seconds": stage_elapsed[key], "detail": detail,
            "findings": found, "findings_total": live_total,
        })

    log(f"ADK supervisor engaged — routing to specialist agents (model: {config.GEMINI_MODEL})")

    def _handle_event(event) -> None:
            author = getattr(event, "author", "") or ""
            content = getattr(event, "content", None)
            if not content or not getattr(content, "parts", None):
                return
            for part in content.parts:
                fcall = getattr(part, "function_call", None)
                fresp = getattr(part, "function_response", None)
                text = getattr(part, "text", None)
                if fcall is not None and getattr(fcall, "name", None):
                    name = fcall.name
                    if name == "transfer_to_agent":
                        target = str((fcall.args or {}).get("agent_name", ""))
                        log(f"supervisor -> {target}")
                        key = AGENT_STAGE.get(target)
                        if key:
                            stage_begin(key)
                    elif name in TOOL_STAGE:
                        stage_begin(TOOL_STAGE[name])
                        log(f"{author}: calling {name}()")
                elif fresp is not None and getattr(fresp, "name", None) in TOOL_STAGE:
                    name = fresp.name
                    key = TOOL_STAGE[name]
                    resp = fresp.response or {}
                    rstatus = str(resp.get("status", "ok"))
                    if name == "fetch_page_text_snapshot":
                        # ai stage stays open until the geo agent finishes reasoning.
                        log("ground truth captured — geo_aeo agent reasoning over buyer questions")
                        continue
                    if name == "capture_viewport_screenshots" and rstatus == "ok" and not early_shots:
                        # import captures immediately so the live preview works
                        early_shots.extend(_import_shots(resp, run_dir, log))
                    count = _resp_count(name, resp)
                    if rstatus == "blocked":
                        log(f"GUARDRAIL BLOCKED {name}: {str(resp.get('reason'))[:140]}")
                        stage_end(key, "degraded", "blocked by safety guardrail")
                    elif rstatus == "error":
                        stage_end(key, "failed", str(resp.get("error"))[:200])
                    else:
                        detail = {
                            "capture_viewport_screenshots": f"{len(resp.get('breakpoints') or {})} viewports captured",
                            "run_axe_core_audit": f"{count} findings (WCAG 2.2 + silent failures)",
                            "run_lighthouse_audit": "source: lighthouse-cli",
                            "test_form_boundaries": f"{count} validation findings; 0 submissions made",
                        }.get(name, "tool run complete")
                        stage_end(key, "ok", detail, count)
                elif text:
                    if author == "qa_supervisor_agent":
                        supervisor_text.append(text)
                    elif author == "geo_aeo_agent":
                        geo_text.append(text)
                    snippet = text.strip().replace("\n", " ")
                    if snippet:
                        log(f"{author}: {snippet[:150]}")

    # The ADK event stream must be consumed inside ONE task context (async
    # generators + per-read wait_for would hop contexts and break telemetry
    # detach). Pump events into a queue; apply the stall watchdog on reads.
    queue: asyncio.Queue = asyncio.Queue()

    async def _pump() -> None:
        try:
            async for event in runner.run_async(user_id=user_id, session_id=scan_id, new_message=message):
                await queue.put(("event", event))
            await queue.put(("done", None))
        except Exception as exc:  # surfaced as a degraded scan, not a hang
            await queue.put(("error", exc))

    pump = asyncio.create_task(_pump())

    async def _drive_graph() -> None:
        while True:
            kind, payload = await asyncio.wait_for(queue.get(), timeout=config.ADK_STALL_TIMEOUT)
            if kind == "done":
                return
            if kind == "error":
                raise payload
            _handle_event(payload)

    async def _consume_stream(stream) -> None:
        """Pump one ADK event stream through the queue consumer."""
        queue2: asyncio.Queue = asyncio.Queue()

        async def _p() -> None:
            try:
                async for event in stream:
                    await queue2.put(("event", event))
                await queue2.put(("done", None))
            except Exception as exc:
                await queue2.put(("error", exc))

        task = asyncio.create_task(_p())
        try:
            while True:
                kind, payload = await asyncio.wait_for(queue2.get(), timeout=config.ADK_STALL_TIMEOUT)
                if kind == "done":
                    return
                if kind == "error":
                    raise payload
                _handle_event(payload)
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    graph_ok = True
    try:
        await asyncio.wait_for(
            _consume_stream(runner.run_async(user_id=user_id, session_id=scan_id, new_message=message)),
            timeout=config.ADK_TOTAL_BUDGET,
        )
    except asyncio.TimeoutError:
        graph_ok = False
        log("watchdog: supervisor graph stalled or exceeded its budget")
    except Exception as exc:
        graph_ok = False
        log(f"watchdog: supervisor graph ended with {type(exc).__name__}: {exc}")

    # ---- baton-pass fallback ----------------------------------------------
    # The supervisor is an LLM: it can drop the baton (truncated turn, missed
    # transfer, early exit). When that happens we run the missing specialists
    # DIRECTLY, in the canonical order, and say so in the audit trail. Agents
    # still do the work; the scheduler is just code instead of prose.
    AGENT_ORDER = [
        ("visual_qa_agent", "screenshots"),
        ("a11y_perf_agent", "accessibility"),
        ("forms_agent", "forms"),
        ("geo_aeo_agent", "ai"),
    ]
    agent_by_name = {
        "visual_qa_agent": adk_agents.visual_qa_agent,
        "a11y_perf_agent": adk_agents.a11y_perf_agent,
        "forms_agent": adk_agents.forms_agent,
        "geo_aeo_agent": adk_agents.geo_aeo_agent,
    }
    # vitals shares a specialist with accessibility.
    stage_agent = {"screenshots": "visual_qa_agent", "accessibility": "a11y_perf_agent",
                   "vitals": "a11y_perf_agent", "forms": "forms_agent", "ai": "geo_aeo_agent"}

    def _missing_agents() -> list[str]:
        missing: list[str] = []
        for agent_name, _ in AGENT_ORDER:
            owned = [k for k, a in stage_agent.items() if a == agent_name]
            if any(stage_status.get(k) not in ("ok",) for k in owned) and agent_name not in missing:
                missing.append(agent_name)
        return missing

    ran_fallback: list[str] = []
    for agent_name in _missing_agents():
        agent = agent_by_name[agent_name]
        for key in [k for k, a in stage_agent.items() if a == agent_name]:
            stage_begin(key)
        log(f"baton-pass: supervisor skipped {agent_name} - running it directly (deterministic fallback)")
        direct_runner = Runner(agent=agent, app_name=app_name, session_service=session_service)
        direct_msg = genai_types.Content(
            role="user", parts=[genai_types.Part(text=f"Audit this target URL: {url}")])
        try:
            await asyncio.wait_for(
                _consume_stream(direct_runner.run_async(
                    user_id=user_id, session_id=scan_id, new_message=direct_msg)),
                timeout=config.ADK_STALL_TIMEOUT,
            )
            ran_fallback.append(agent_name)
        except asyncio.TimeoutError:
            log(f"baton-pass: {agent_name} exceeded its budget")
        except Exception as exc:
            log(f"baton-pass: {agent_name} failed: {type(exc).__name__}: {exc}")

    # ---- deterministic result assembly from stashed tool payloads ---------
    session = await session_service.get_session(app_name=app_name, user_id=user_id, session_id=scan_id)
    state = dict(getattr(session, "state", {}) or {}) if session else {}
    raw = {k[4:]: v for k, v in state.items() if isinstance(k, str) and k.startswith("raw:")}
    log(f"tool payloads collected: {', '.join(sorted(raw)) or 'none'}")

    shots_payload = raw.get("capture_viewport_screenshots") or {}
    axe_payload = raw.get("run_axe_core_audit") or {}
    lh_payload = raw.get("run_lighthouse_audit") or {}
    forms_payload = raw.get("test_form_boundaries") or {}
    geo_report = "\n".join(geo_text)

    shots: list[ScreenshotMeta] = list(early_shots)
    if not shots and shots_payload.get("status") == "ok":
        shots = _import_shots(shots_payload, run_dir, log)

    findings: list[Finding] = []
    findings += _visual_findings(shots_payload)
    findings += _axe_findings(axe_payload)
    vitals_data: dict[str, Any] = {}
    if lh_payload.get("status") == "ok":
        vitals_data = _vitals_from(lh_payload)
        findings += _perf_findings(lh_payload)
    findings += _forms_findings(forms_payload)
    geo_found = _geo_findings(geo_report)
    findings += geo_found

    # ---- finalize every stage honestly (never hide a routing miss) --------
    has_data = {
        "screenshots": bool(shots),
        "accessibility": bool(axe_payload),
        "vitals": bool(vitals_data),
        "forms": bool(forms_payload),
        "ai": bool(geo_report.strip()),
    }
    final_detail = {
        "screenshots": f"{len(shots)} viewports captured",
        "accessibility": f"{len(_axe_findings(axe_payload))} findings (WCAG 2.2 + silent failures)",
        "vitals": f"source: {vitals_data.get('source', 'unavailable')}",
        "forms": f"{len(_forms_findings(forms_payload))} validation findings; 0 submissions made",
        "ai": f"{len(geo_found)} findings; model: {config.GEMINI_MODEL}",
    }
    for key, _label in STAGE_LABELS:
        status = stage_status.get(key)
        if status in ("ok", "failed", "degraded") and key != "ai":
            continue  # already settled live by its tool response
        if has_data[key]:
            found = len(_geo_findings(geo_report)) if key == "ai" else stage_counts.get(key, 0)
            if key == "ai":
                stage_end(key, "ok", final_detail[key], found)
            else:
                # settle stages whose tool ran but whose response we never saw
                stage_end(key, "ok", final_detail[key])
        else:
            reason = ("specialist never completed — LLM routing miss" if status == "running"
                      else "specialist never ran — LLM routing miss")
            stage_end(key, "degraded", reason)

    # Patch settled "tool run complete" details with the real summaries.
    # (Stage events already streamed; StageResult carries the final wording.)
    stage_results = [
        StageResult(key=k, label=STAGE_LABEL[k],
                    status=stage_status.get(k, "degraded"),
                    elapsed_seconds=stage_elapsed.get(k, 0.0),
                    detail=final_detail[k])
        for k, _ in STAGE_LABELS
    ]

    # ---- aggregate, synthesis, artifacts ----------------------------------
    aggregate = _extract_json("\n".join(supervisor_text)) or {}
    if aggregate:
        log("supervisor aggregate received")

    emit({"type": "log", "message": "deduplicating findings and writing the executive summary"})
    findings = dedup_findings(findings)
    counts = severity_counts(findings)
    synth = await synthesis.synthesize(url, findings, counts, vitals_data, log)

    top_risks = aggregate.get("top_risks")
    if not (isinstance(top_risks, list) and top_risks and all(isinstance(t, str) for t in top_risks)):
        top_risks = synth["top_risks"]

    result = ScanResult(
        scan_id=scan_id,
        target_url=url,
        final_url=url,
        scanned_at=_now_iso(),
        elapsed_seconds=round(time.monotonic() - started, 1),
        user_agent=config.USER_AGENT,
        model=config.GEMINI_MODEL,
        severity_counts=counts,
        findings=findings,
        top_risks=[str(t) for t in top_risks][:5],
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
                "No submit code path exists. The ADK before_tool_callback guardrail hard-blocks "
                "any submit intent, and the forms tool never locates or clicks a submit control."
            ),
            "data_submitted": False,
            "ai_model": config.GEMINI_MODEL,
            "ai_model_policy": "Every AI layer runs on gemini-flash-latest only.",
            "orchestrated_by": "Google ADK — qa_supervisor_agent + visual/a11y_perf/forms/geo_aeo specialists",
            "direct_run_fallback": ran_fallback,
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
