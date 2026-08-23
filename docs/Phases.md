# Phases — build order and status

> Phases 1–6 were built on the original procedural pipeline; that era is
> preserved untouched on branch `procedural-pipeline`. Phase 7 rebuilt the
> orchestration on Google ADK and is what ships on `main` today.

## Phase 1 — Skeleton & safety rails ✅ *(procedural era)*
Config (SafetyConfig + RunConfig), data models, crawler with robots.txt
fail-closed, throttle, honest User-Agent. *Exit: pipeline shape exists,
nothing hits the site unsafely.*

## Phase 2 — Four specialist checks ✅ *(procedural era)*
visual QA (rubric vision judging), forms (boundary cases + NEVER_SUBMIT),
GEO/AEO (static schema diff + dynamic LLM cross-check), a11y/perf
(axe + Lighthouse + PageMonitor). *Exit: uniform Findings from every layer.*

## Phase 3 — Persistence, synthesis, report ✅ *(procedural era)*
Local JSON store, dedupe/rank/render. *Exit: report generated from real
scan artifacts.*

## Phase 4 — Hardening pass ✅ *(procedural era)*
Hidden forms skipped; axe-core bundled locally via npm (site CSP can't block
injection); Lighthouse CLI verified; test suite expanded.

## Phase 5 — De-cloud & deliverable ✅ *(procedural era)*
Removed Cloud Run Jobs/Firestore/deploy scaffolding; trimmed to local-only;
built the founder-facing PDF with embedded screenshots.

## Phase 6 — Real AI layer verified ✅ *(procedural era)*
Gemini key wired and live-verified; pricing-page classification fixed so the
dynamic GEO/AEO cross-check fires; reproducible visual findings + genuine
answer-engine mismatches confirmed.

## Phase 7 — Google ADK refactor ✅ *(current, on `main`)*

Rebuilt orchestration on **google-adk**: `qa_supervisor_agent` + four
specialist `LlmAgent`s (`visual_qa_agent`, `forms_agent`, `geo_aeo_agent`,
`a11y_perf_agent`) with model-driven transfers and a `before_tool_callback`
form-submission guardrail. Execution layer (`tools.py`) wraps the shared
`xoxoday_qa` core; `main.py` seeds session state, harvests every tool payload
from the event stream, and aggregates the structured log; `generate_pdf.py`
renders the executive PDF.

Four real bugs surfaced and were fixed during the refactor:

1. Sync Playwright called inside the asyncio event loop → all tools now wrap
   their blocking implementations in `asyncio.to_thread`.
2. Guardrail crashed on ADK's kwarg contract → callback signature uses
   `tool_context=` (positional assumptions broke silently).
3. Guardrail evasion gaps → detection now matches an escape-normalized intent
   blob of tool name **and** arguments, including click verbs aimed at submit
   controls; adversarial suite passes 10/10.
4. Supervisor surrendered early after the first specialist returned → explicit
   handback protocol (specialists end with `transfer_to_agent(qa_supervisor_agent)`)
   plus temperature=0 orchestration.

Generalization work: per-domain buyer questions (`BUYER_QUESTIONS_BY_DOMAIN` +
`{buyer_questions}` session-state templating), filename-agnostic PDF naming
(`page_slug`). Print bug fixed: tall screenshots pre-sliced into page-sized
JPEG chunks (Chromium's PDF tiler black-bands multi-page-tall images).

Repo split: `procedural-pipeline` branch keeps the legacy era; `main` was
rewritten (README, requirements, gitignore, tests trimmed to 9) and force-
pushed after catching a blanket `git add -A` resurrecting untracked legacy
files. Verified: origin has no legacy modules and no secrets; local legacy
copies remain for reference, guarded by `.git/info/exclude`.

*Exit criteria met:* full plum-pricing run 5/5 tools ok (~2–3 min; 2 critical /
5 high / 27 medium / 1 info); generalization proof on syynapse.vercel.app
(5/5 tools ok, real findings, per-domain buyer questions injected).

## Phase 8 — Candidates (not started)

- Multi-page/full-sitemap runs with per-run output directories
- Scheduled runs (Task Scheduler/cron wrapper around `main.py`)
- Second answer engine for GEO/AEO cross-engine consistency diff
- Trend tracking: diff severity counts across successive `adk_run_*.json` logs
- Host `adk web` dev UI using the exported `root_agent`
- Hosted screenshot evidence beyond the PDF

## Rule for any AI resuming this project

Read Memory.md first. Do not redo completed phases. `main` is the ADK
pipeline; `procedural-pipeline` is a frozen snapshot — never merge it forward.
New work = pick from Phase 8 or a user request, one phase-sized step at a
time, tests green before committing.
