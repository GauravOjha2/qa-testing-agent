# Phases — build order and status

> Phases 1–6 are complete. The project is in a submittable, working state.
> Phase 7+ is future work, intentionally not started.

## Phase 1 — Skeleton & safety rails ✅
Config (SafetyConfig/RunConfig), data models, crawler with robots.txt
fail-closed, throttle, honest User-Agent. *Exit: pipeline shape exists, nothing
hits the site unsafely.*

## Phase 2 — Four specialist agents ✅
visual_qa (rubric vision judge), forms_agent (boundary cases + NEVER_SUBMIT),
geo_aeo_agent (static schema diff + dynamic LLM cross-check), a11y_perf_agent
(axe + Lighthouse + PageMonitor). *Exit: each agent returns uniform Findings.*

## Phase 3 — Persistence, synthesis, HTML report ✅
store.py local JSON, synthesis dedupe/rank/render. *Exit: report.html generated
from real scan artifacts.*

## Phase 4 — Hardening pass ✅
Hidden forms skipped (no 30s hangs on invisible login/reset fields); axe-core
bundled locally via npm (site CSP can't block injection); Lighthouse CLI
installed and verified; test suite expanded to 11.

## Phase 5 — De-cloud & deliverable ✅
Removed Cloud Run Jobs/Firestore/deploy scaffolding and orchestrator; trimmed
requirements to local-only; rewrote README; purged stale/bot-blocked scan
artifacts; built scripts/generate_report.py producing the founder-facing PDF
with embedded screenshots, exec summary, methodology, limitations, appendix.

## Phase 6 — Real AI layer verified ✅
.env support added (gitignored); Gemini key wired and live-verified;
classification bug fixed (`/plum-pricing/` → pricing_roi) so the dynamic GEO/AEO
cross-check fires on product/pricing pages; mock mode labeled explicitly.
Full rerun produced reproducible visual findings + 2 genuine answer-engine
mismatches. Report regenerated and pushed.

## Phase 7 — Candidate next steps (not started)
- Multi-page / full-sitemap run with per-run output directories
- Nightly schedule (Task Scheduler/cron wrapper around run_local_demo.py)
- Migrate `google-generativeai` → `google-genai` (current SDK is deprecated but functional)
- Add second answer engine when budget allows (cross-engine consistency diff)
- Screenshot evidence hosted alongside findings if sharing beyond PDF
- Trend tracking: store severity counts per run, flag regressions between runs

## Rule for any AI resuming this project

Read Memory.md first. Do not redo completed phases. New work = pick from
Phase 7 or a user request, one phase-sized step at a time, tests green before
committing.
