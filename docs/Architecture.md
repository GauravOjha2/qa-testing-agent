# Architecture — QA Testing Agent (Google ADK)

## Pipeline flow

```
adk_qa_pipeline/main.py  (--url <target>)
  │
  ├─► seeds session state {target_url, buyer_questions}
  │
  ├─► qa_supervisor_agent (gemini-flash-latest, temperature=0)
  │     transfers to each specialist exactly once, passing the URL verbatim:
  │
  │     visual_qa_agent ──► capture_viewport_screenshots(url)
  │                          full-page PNGs @ mobile/tablet/desktop
  │                          + deterministic horizontal-overflow probe
  │     a11y_perf_agent ───► run_axe_core_audit(url)      WCAG 2.2 A/AA,
  │                          run_lighthouse_audit(url)    LCP/CLS/INP,
  │                                                       silent failures
  │     forms_agent ───────► test_form_boundaries(url)   boundary/i18n fills,
  │                          [guardrail]                 aria-invalid reads,
  │                                                      submit IMPOSSIBLE
  │     geo_aeo_agent ─────► fetch_page_text_snapshot(url) then self-consistency
  │                          hallucination diff against per-domain questions
  │
  ├─► every specialist ends with transfer_to_agent(qa_supervisor_agent)
  │
  └─► main.py harvests tool responses from the ADK event stream,
      dedupes findings, ranks severity -> local_findings_adk/adk_run_*.json

adk_qa_pipeline/generate_pdf.py
  └─► newest adk_run_*.json -> KPI cards, top risks, evidence screenshots
      (pre-sliced to page-sized chunks), severity cards -> ADK-QA-Report_<slug>.pdf
```

## Folder structure

```
adk_qa_pipeline/
  __init__.py          exports root_agent (adk web compatibility)
  agents.py            4 specialists + supervisor + prevent_form_submit_guardrail
  tools.py             execution layer: robots gate, throttle reuse, axe/Lighthouse/
                       screenshots/forms/ground-truth tools, per-domain buyer questions
  main.py              async runner; harvests event stream; aggregates JSON log
  generate_pdf.py      PDF renderer with page-sized screenshot slicing
src/xoxoday_qa/        shared core the tools import (single source of truth):
  config.py            SafetyConfig + RunConfig; loads .env
  crawler.py           check_robots_allowed (fail-closed), classification helpers
  playwright_utils.py  throttle(), PageMonitor, browser_session(), goto_and_settle(),
                       screenshot_at_breakpoints()
  models.py, dom_utils.py   shared dataclasses / meta reader
tests/test_crawler.py  unit tests for classification, navigation, DOM helpers
docs/                  PRD, Architecture, Rules, Phases, Design, Memory
local_findings_adk/    run artifacts (gitignored): tool payloads + aggregated log
screenshots/local/     breakpoint captures (gitignored; regenerated per run)
.env                   GEMINI_API_KEY - GITIGNORED, never commit
```

Legacy raw-Python pipeline (agents/store/synthesis/scripts) lives on the
`procedural-pipeline` branch, not here.

## Technical stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.13 | team-familiar; Playwright + ADK first-class support |
| Agent framework | google-adk (>=1.0) | LlmAgent sub-agent transfers, before_tool_callback guardrails, state-injected instructions |
| Models | gemini-flash-latest (specialists+supervisor), gemini-pro-latest (GEO/AEO judgment) | fast/cheap routing where determinism matters, stronger reasoning for factual diffing |
| Browser automation | Playwright (sync API inside `asyncio.to_thread`) | real Chromium; worker threads dodge the sync-API-in-async-loop restriction |
| A11y | axe-core 4.10 (npm bundle injected locally) | site CSP can't block a local injection |
| Perf | Lighthouse CLI via npx subprocess | Core Web Vitals without Node API plumbing |
| Persistence | local JSON artifacts per tool call + merged run log | inspectable, diffable, zero infra |
| Report | HTML -> PDF via Playwright `page.pdf()`; Pillow pre-slicing | tall captures can't glitch Chromium's print tiler |

## Key design decisions

- **Aggregation trusts tools, not prose:** main.py harvests every
  `function_response` payload from the event stream; the supervisor's JSON
  summary is decorative, the structured log is authoritative.
- **Guardrail is defense-in-depth:** `prevent_form_submit_guardrail`
  (before_tool_callback, kwarg `tool_context=` in ADK >=1.x) blocks submit
  intent at four levels - submit-named tools, click-intent x submit selectors
  (name OR args, escape-normalized), action="submit" args, and boundary tests
  pointed at a submit control. The tool itself also never touches submit.
- **Deterministic orchestration contract:** supervisor temperature=0 with two
  legal outputs (a transfer call, or the final aggregate only after all four
  completion markers); specialists must end by calling
  `transfer_to_agent(qa_supervisor_agent)` - prose handbacks end the run.
- **Sync Playwright off-loop:** every tool is an `async def` wrapper over
  `asyncio.to_thread(sync_impl)`; worker threads have no running loop.
- **Per-domain configurability via session state:** `{buyer_questions}` is
  injected into the GEO/AEO instruction from state seeded by main.py;
  `BUYER_QUESTIONS_BY_DOMAIN` in tools.py is the single place to customize.
- **State-injection safety:** only geo_aeo's instruction contains a `{state}`
  placeholder; all instructions audited so literal JSON braces pass through
  untouched (`_is_valid_state_name` gate).
- **Robots gate fail-closed, reused:** every tool call runs
  `check_robots_allowed` before navigation; unreachable robots.txt aborts.
- **PDF print-tile workaround:** screenshots are width-normalized and sliced
  into ~1.45 aspect chunks before embedding; multi-page-tall images otherwise
  render black bands in Chromium's printer.
- **Cloud removed deliberately** (see Phases.md); legacy pipeline preserved on
  its own branch rather than deleted from history.
