# Phases — build order and status

## Era 1 — procedural pipeline (superseded)

Raw-Python crawler + four specialist agents + a Pillow/Chromium report. It proved the
detection logic (axe, Lighthouse, form probing, GEO/AEO) but the orchestration was
hand-wired and the UI was a single form posting to a slow request.

## Era 2 — Google ADK orchestration (superseded, removed)

An LLM supervisor agent (`gemini-flash-latest`) that transferred to each specialist in turn
and wrote run artifacts under `local_findings_adk/`. Interesting to build, wrong tool for
the job: the scan is a fixed, deterministic pipeline, so an LLM supervisor added latency,
non-determinism and a large dependency for no accuracy gain. **Removed in Era 3.**

## Era 3 — the shipped product

| Phase | Scope | Status |
|---|---|---|
| 1. Engine skeleton | `app/config.py`, models, `RateLimiter`, robots.txt fail-closed | ✅ |
| 2. Capture agent | three viewports, lazy-load scroll pass, overflow probe, Pillow thumbnails | ✅ |
| 3. Audit agent | axe-core WCAG 2.2 A/AA with evidence nodes | ✅ |
| 4. Audit agent — vitals | Lighthouse CLI + `PerformanceObserver` fallback, threshold grading | ✅ |
| 5. Guard agent | three-layer no-submit guardrail, boundary/invalid/i18n probes | ✅ |
| 6. Intel agent | ground-truth scrape, multimodal GEO/AEO + visual review, synthesis | ✅ |
| 7. Orchestrator | stage isolation, timeouts, dedup, deterministic IDs, JSON + PDF artifacts | ✅ |
| 8. Web product | FastAPI, SSE job stream, artifact endpoints, SSRF guard, CORS | ✅ |
| 9. Report | A4 PDF: dark cover, KPI cards, finding cards, gallery, safety statement | ✅ |
| 10. Verification | 11 offline unit tests + `scripts/verify_e2e.py` against a local fixture | ✅ |
| 11. Frontend redesign | agent-tree landing, rail progress, results workspace, design system | ✅ |
| 12. Deployment | Dockerfile + Cloud Run for the engine, `vercel.json` + build step for the UI | ✅ |
| 13. Cleanup | legacy ADK/procedural code, stale artifacts and docs removed | ✅ |

### Known limits (deliberately not built)

* Single page per scan — no crawl, no sitemap, no auth-gated routes.
* Lighthouse numbers are lab measurements on one profile; INP needs field data, so TBT is
  reported as its lab proxy and the report says so.
* Jobs and artifacts are in-process and expire after two hours; multi-instance deployments
  need external state (see [Architecture](Architecture.md#concurrency-and-isolation)).
* No historical diffing between scans yet, even though findings are reproducible enough to
  support it.
