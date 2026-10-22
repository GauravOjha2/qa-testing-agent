# CHANGES.md — change log

Every code/config change is logged here with what changed, where, and the
reasoning, so each decision can be reviewed or reverted later.

---

## 2026-10-22 — Fix failing Performance stage (Lighthouse on Cloud Run)

**Symptom:** Every ADK scan's Performance stage failed after ~20s with a raw
`CalledProcessError: Command '['/usr/bin/npx', '--yes', 'lighthouse', ...]`
dumped into the UI, and Core Web Vitals were never captured.

**Root cause:** The ADK tool `_run_lighthouse_audit_sync` (a) shelled out via
`npx --yes lighthouse` even though the Docker image installs `lighthouse@12`
globally, (b) never set `CHROME_PATH`, so Lighthouse's chrome-launcher could
not find a browser — the container has no system Chrome, only Playwright's
Chromium under `/ms-playwright`, and (c) surfaced the raw Python exception
text to the report UI.

### Change 1 — `adk_qa_pipeline/tools.py`
- Added `_lighthouse_command()`: prefers the globally installed `lighthouse`
  binary; `npx --yes lighthouse` (which re-resolves the package from the npm
  registry on every cold start) is kept only as a last resort.
  **Why:** the image already ships Lighthouse; using it removes network
  dependency and startup latency, and matches how the Dockerfile intends the
  stage to run.
- Set `CHROME_PATH` to the Playwright-installed Chromium via a new shared
  helper, and switched `--headless` to `--headless=new`.
  **Why:** Cloud Run has no system Chrome. `CHROME_PATH` is the supported
  chrome-launcher override; new headless is the maintained mode compatible
  with current Chromium.
- On failure the tool now returns a clean one-line error (with only the
  stderr tail) instead of the raw command dump.
  **Why:** the exception text leaked internal paths/commands into the
  customer-facing report; the stderr tail keeps the useful diagnostic.
- **Framework boundary respected:** no new agents, no routing changes, no
  fallback to the legacy engine. `a11y_perf_agent` still calls
  `run_lighthouse_audit()` exactly as before — only the tool's launch
  internals changed.

### Change 2 — `src/xoxoday_qa/playwright_utils.py`
- Added `chromium_path()`: locates Playwright's Chromium across the Linux
  container layout (`PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`) and Windows/
  macOS dev layouts.
  **Why:** `adk_qa_pipeline/tools.py` already delegates browser plumbing to
  this module, so the helper lives where both pipelines can reach it.
  `app/stages/vitals.py` keeps its own copy deliberately — `app/` has no
  dependency on `src/` today and adding one for a 20-line lookup was judged
  riskier than the small duplication.

## 2026-10-22 — Mitigate missing-artifact 404s (Option A band-aid)

**Symptom:** Broken screenshot previews and `report.json` downloads failing
with "Couldn't download - No file" after otherwise successful scans.

**Root cause:** No backend storage. Job records live in process memory and
artifacts (shots, report.json/pdf) on the container's ephemeral disk. Any
request routed to a different/new Cloud Run instance 404s.

### Change 3 — `docs/DEPLOYMENT.md`
- Deploy command now includes `--max-instances 1 --session-affinity` and the
  notes explain the trade-off and the optional `--min-instances 1`.
  **Why:** one warm instance + sticky clients means every artifact request
  hits the instance that produced it. This is config only — zero code change.
  The documented long-term fix (GCS bucket for artifacts / Redis-backed
  JobStore) is unchanged and still recommended.

## Not changed (deliberately)
- Baton-pass fallback in `app/adk_engine.py` — working as designed; the
  supervisor LLM occasionally drops routing and the deterministic fallback
  re-runs the agent. Not an error.
- `app/stages/vitals.py` observer fallback — untouched legacy core engine.

---

## 2026-10-22 — DebugBundle error capture (user's DebugBundle membership)

**Goal:** when production breaks, capture the failure + context automatically
as an agent-readable "debug bundle" instead of relying on screenshots of the
UI. API verified against the installed SDK (`debugbundle-python` 2.0.1).

### Change 4 — `server.py`
- Added a guarded init block after app creation: reads
  `DEBUGBUNDLE_PROJECT_TOKEN` / `DEBUGBUNDLE_ENVIRONMENT`, calls
  `debugbundle.init()`, `capture_exceptions()` (process-level uncaught
  errors) and `instrument_fastapi()` (the SDK's own ASGI middleware, which
  also hooks error-level logging). Wrapped in try/except so a missing package
  or bad token can never break the scanner; no token = capture fully off.
- Added an explicit `capture_exception(exc, context={scan_id, url})` in
  `_drive()`'s scan-failure handler.
  **Why:** scan crashes are caught and surfaced to the UI, so the global
  hooks would never see them — this is exactly the class of failure (e.g. the
  Lighthouse crash) we want bundles for.
- Deliberately skipped `capture_async()`: it calls
  `asyncio.get_event_loop()`, which is fragile at module import time under
  uvicorn, and its value is already covered by the explicit `_drive` capture.

### Change 5 — `requirements.txt`
- Added `debugbundle-python>=2.0.1`.
  **Why:** the SDK ships in the container image so Cloud Run captures errors;
  it stays inert locally unless the token env var is set.

### Change 6 — `docs/DEPLOYMENT.md`
- Documented `DEBUGBUNDLE_PROJECT_TOKEN` / `DEBUGBUNDLE_ENVIRONMENT` in the
  env-var table.
  **Why:** the token is a secret config value; it belongs in deploy docs next
  to `GEMINI_API_KEY`, never in the repo.

---

## 2026-10-22 — chromium_path() missed the Chrome-for-Testing layout

**Caught by:** reading the Cloud Build log, which showed Playwright 1.64
downloads "Chrome for Testing 156.x" to `/ms-playwright/chromium-1248`.

### Change 7 — `src/xoxoday_qa/playwright_utils.py`
- Added glob patterns `chromium-*/chrome-linux64/chrome` and
  `chromium_headless_shell-*/chrome-linux64/headless_shell` to
  `chromium_path()`, keeping the legacy `chrome-linux` pattern.
  **Why:** newer Playwright packages Chromium as Chrome for Testing under
  `chrome-linux64/`, not `chrome-linux/`. Without this, the helper would
  silently return None in the container and the Lighthouse fix (Change 1)
  would have been a no-op. Found before deploying, so only one extra rebuild.
