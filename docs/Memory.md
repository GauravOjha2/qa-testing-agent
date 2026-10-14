# Memory — living context for any session

> Read this before touching the code. Last updated: 2026-10-14.

## What this project is

**SiteSentinel** — a public web app where anyone pastes a URL and receives an executive
website QA report. Four headless agents (Capture, Audit, Guard, Intel) run five stages
against one page and produce an A4 PDF plus structured JSON.

## Current state

* Engine, web app, report and frontend are complete and verified end to end.
* `python -m pytest` → 11 passed. `python scripts/verify_e2e.py` → all checks passed against
  `tests/fixture_site` (5 stages `ok`, 17 findings deduplicated, `forms_submitted == 0`,
  three viewports captured, ~0.5 MB multi-page PDF, JSON + captures served).
* Legacy Era-1/Era-2 code (procedural pipeline, Google ADK pipeline, the old `webapp.py`
  form UI, old run artifacts and PDFs) has been **deleted**. `main` contains only the
  product described in [Architecture](Architecture.md).
* Deployment is prepared but not executed: engine → Cloud Run (`Dockerfile`), UI → Vercel
  (`vercel.json` + `scripts/build-vercel.mjs`). See [DEPLOYMENT](DEPLOYMENT.md).

## Environment notes (this machine)

* Python 3.13 at `C:\Users\gaura\AppData\Local\Programs\Python\Python313\python.exe`
  (`py`/`python` on PATH are the broken Windows Store stubs — always use the full path).
* Playwright Chromium is installed under `%LOCALAPPDATA%\ms-playwright`.
* No Lighthouse binary is installed globally. If `npx` can supply it, local runs use the CLI;
  otherwise they use the observer fallback and report `vitals: degraded`. The container installs
  Lighthouse 12, where the stage is `ok`.
* `GEMINI_API_KEY` lives in `.env` (gitignored). The AI stages work.
* Local scans of external sites need `SITESENTINEL_ALLOW_PRIVATE_TARGETS=1` only when the
  target is on loopback (the fixture site). Outbound DNS is unreliable on this box.

## Local run recipe

```powershell
python -m http.server 8099 --directory tests/fixture_site      # terminal 1
$env:SITESENTINEL_ALLOW_PRIVATE_TARGETS = "1"
python -m uvicorn server:app --port 8080                        # terminal 2
python scripts/verify_e2e.py http://127.0.0.1:8080 http://127.0.0.1:8099/   # terminal 3
```

## Invariants to protect

Read [Rules](Rules.md). The three that matter most: no form submission code path, robots.txt
fail-closed, and every AI layer on `gemini-flash-latest` only.

## Obvious next steps

1. Persist jobs + artifacts outside the process (Redis/Firestore + GCS) for multi-instance.
2. Scan-result diffing between two runs of the same URL.
3. Optional multi-page mode (crawl a small set of same-origin pages, aggregate findings).
4. Wire `scripts/verify_e2e.py` into CI with the fixture site as a service container.
