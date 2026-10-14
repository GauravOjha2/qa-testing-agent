# ADK Engine — the agent graph as the orchestrator

`SITESENTINEL_ENGINE=adk` (default) runs the scan through the **Google ADK agent
graph** instead of the deterministic pipeline (`=core`). Both engines emit the
exact same SSE event vocabulary and produce the same `ScanResult`, so the
frontend, the PDF renderer, and the e2e verifier cannot tell them apart.

## Topology

```
POST /api/scan
   │
   ▼
app/adk_engine.py  — the bridge (this is the piece to study)
   │  Runner + InMemorySessionService, one session per scan
   ▼
qa_supervisor_agent (LlmAgent, gemini-flash-latest, temp 0)
   │  transfer_to_agent × 4, strict completion-marker protocol
   ├── visual_qa_agent        → capture_viewport_screenshots()
   ├── a11y_perf_agent        → run_axe_core_audit() + run_lighthouse_audit()
   ├── forms_agent            → test_form_boundaries()   [guardrailed]
   └── geo_aeo_agent          → fetch_page_text_snapshot() + self-consistency diff
```

## The three ideas that make it production-shaped

1. **Agents decide what to run; code decides what is true.**
   Tools return compact summaries to the model (counts + top titles) while the
   full structured payload is stashed in ADK session state
   (`tool_context.state["raw:<tool>"]`). The bridge builds every `Finding`,
   the vitals block, the severity counts, and the PDF from those payloads —
   never from LLM prose. This also keeps per-scan token cost low
   (~12–15 flash calls, all temperature 0, capped outputs).

2. **Safety is a callback, not a prompt.**
   `prevent_form_submit_guardrail` (a `before_tool_callback` on the forms
   agent) hard-blocks any tool call with submit intent before it executes.
   The tool itself never locates a submit control. `forms_submitted` is 0 by
   construction, and blocked calls stream into the UI telemetry as first-class
   events.

3. **The supervisor can drop the baton; the scheduler catches it.**
   LLM routing is probabilistic: a truncated turn or missed transfer can end
   the graph early. The bridge detects stages that never settled and runs
   those specialists **directly** (canonical order, one Runner each), logging
   `baton-pass: supervisor skipped <agent> — running it directly`. The report's
   safety block records which agents needed the fallback
   (`direct_run_fallback`). Nothing is hidden.

## Event translation (ADK → product SSE)

| ADK event | Product event |
|---|---|
| `transfer_to_agent(visual_qa_agent)` | `stage: screenshots running` |
| function_call `capture_viewport_screenshots` | `stage: screenshots running` |
| function_response (status ok) | `stage: <key> ok` + findings count |
| function_response (status blocked/error) | `stage: degraded/failed` + guardrail log |
| geo_aeo_agent text | `ai` stage stays open until reasoning completes |
| supervisor final JSON | `top_risks` (with deterministic synthesis fallback) |

## Watchdogs

- `ADK_STALL_TIMEOUT` (300s): max silence between agent events.
- `ADK_TOTAL_BUDGET` (780s): hard cap for the supervisor graph.
- Per-direct-run cap: one stall timeout each.
- The event stream is consumed through a queue pump inside a single task
  context (async generators + per-read `wait_for` would hop contexts).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SITESENTINEL_ENGINE` | `adk` | `adk` (agent graph) or `core` (deterministic pipeline) |
| `ADK_STALL_TIMEOUT` | 300 | seconds between agent events before watchdog fires |
| `ADK_TOTAL_BUDGET` | 780 | hard cap for the supervisor graph |
| `GEMINI_API_KEY` | – | drives every agent (gemini-flash-latest only) |

If the ADK import fails at startup the server logs a loud warning and falls
back to `core` (a regression test pins the import so this cannot go silent).

## Cost & latency vs core

Measured on the fixture site: ~140s vs ~60s core, ~12–15 gemini-flash calls
vs 2. The overhead is the price of LLM routing; the cap on tool summaries and
output tokens keeps it minimal. For a portfolio piece the tradeoff is the
point: the same report, produced by an agent graph you can explain end to end.

## Verify

```powershell
$env:SITESENTINEL_ALLOW_PRIVATE_TARGETS = "1"
$env:SITESENTINEL_ENGINE = "adk"
python -m uvicorn server:app --port 8080
python scripts/verify_e2e.py http://127.0.0.1:8080 http://127.0.0.1:8099/
python -m pytest   # includes tests/test_adk_bridge.py
```
