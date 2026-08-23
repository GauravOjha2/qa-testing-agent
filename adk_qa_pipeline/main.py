"""Orchestrator: trigger the qa_supervisor_agent and aggregate structured JSON.

Usage (from the repo root):
    python adk_qa_pipeline/main.py --url https://signup.xoxoday.in/plum-pricing/

Requires GEMINI_API_KEY in the environment or repo-root .env. The run is
asynchronous end-to-end: the supervisor transfers to each specialist agent,
each specialist invokes its deterministic tools, and this script harvests
every tool response from the ADK event stream - so the final JSON log is
built from ground-truth tool payloads, not from trusting the LLM's prose.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adk_qa_pipeline.agents import qa_supervisor_agent  # noqa: E402
from adk_qa_pipeline.tools import (  # noqa: E402
    ARTIFACTS_DIR,
    get_buyer_questions,
)
from xoxoday_qa.config import SAFETY  # noqa: E402  (also loads .env)

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types as genai_types  # noqa: E402

APP_NAME = "xoxoday_qa_adk"
USER_ID = "local_operator"
DEFAULT_URL = "https://signup.xoxoday.in/plum-pricing/"


async def run_supervisor(target_url: str) -> dict:
    """Drive the supervisor through one full QA cycle and harvest events."""
    runner = InMemoryRunner(agent=qa_supervisor_agent, app_name=APP_NAME)
    questions_text = "\n".join(
        f"- {q}" for q in get_buyer_questions(target_url)
    )
    session = await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state={
            "target_url": target_url,
            "buyer_questions": questions_text,
        },
    )

    prompt = (
        f"Run the full QA suite against this target URL: {target_url}\n"
        "Follow your orchestration protocol exactly."
    )

    harvested: list[dict] = []
    final_text_parts: list[str] = []

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=genai_types.Content(
            role="user", parts=[genai_types.Part(text=prompt)]
        ),
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            fr = getattr(part, "function_response", None)
            response = getattr(fr, "response", None) if fr else None
            if isinstance(response, dict) and (
                "tool" in response or response.get("status") == "blocked"
            ):
                harvested.append(response)
            text = getattr(part, "text", None)
            if text and event.is_final_response():
                final_text_parts.append(text)

    return {
        "tool_payloads": harvested,
        "supervisor_summary": "".join(final_text_parts).strip(),
    }


def aggregate(target_url: str, run_result: dict, elapsed_s: float) -> dict:
    """Merge ground-truth tool payloads into one structured log entry."""
    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()
    tool_runs: list[dict] = []

    for payload in run_result["tool_payloads"]:
        tool_runs.append({
            "tool": payload.get("tool") or payload.get("blocked_tool", "unknown"),
            "url": payload.get("url"),
            "status": payload.get("status"),
        })
        for f in payload.get("findings") or []:
            key = (str(f.get("title")), str(f.get("detail", ""))[:80])
            if key in seen:
                continue
            seen.add(key)
            findings.append({**f, "source_tool": payload.get("tool")})

    severity_counts: dict[str, int] = {}
    for f in findings:
        sev = f.get("severity", "info")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    order = ["critical", "high", "medium", "low", "info"]
    top_risks = [
        f.get("title", "")
        for f in sorted(
            findings,
            key=lambda f: order.index(f.get("severity", "info")),
        )
        if f.get("severity") in ("critical", "high")
    ][:5]

    return {
        "meta": {
            "pipeline": "adk_qa_pipeline",
            "app_name": APP_NAME,
            "target_url": target_url,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed_s, 1),
            "safety": {
                "user_agent": SAFETY.resolved_user_agent(),
                "robots_txt": "fail-closed enforced per tool call",
                "form_submission": "blocked by guardrail + tool policy",
                "throttle_seconds": SAFETY.min_delay_seconds,
            },
        },
        "tool_runs": tool_runs,
        "severity_counts": severity_counts,
        "top_risks": top_risks,
        "findings": findings,
        "supervisor_summary": run_result["supervisor_summary"],
    }


async def main_async(target_url: str) -> Path:
    print(f"Target: {target_url}")
    print("Supervisor starting full suite "
          "(visual -> a11y/perf -> forms -> geo/aeo)...")

    started = time.monotonic()
    try:
        run_result = await run_supervisor(target_url)
    except Exception as exc:
        print(f"FATAL: supervisor run failed: {type(exc).__name__}: {exc}")
        raise

    elapsed = time.monotonic() - started
    log = aggregate(target_url, run_result, elapsed)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = ARTIFACTS_DIR / f"adk_run_{stamp}.json"
    out_path.write_text(json.dumps(log, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    print(f"\nDone in {elapsed:.1f}s")
    print(f"Tool runs: {len(log['tool_runs'])} | "
          f"Findings: {log['severity_counts']} | Top risks: "
          f"{len(log['top_risks'])}")
    print(f"Structured log: {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="ADK multi-agent QA pipeline")
    parser.add_argument("--url", default=DEFAULT_URL,
                        help=f"Target URL to audit (default: {DEFAULT_URL})")
    args = parser.parse_args()
    asyncio.run(main_async(args.url))


if __name__ == "__main__":
    main()
