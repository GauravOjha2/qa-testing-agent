# Memory — living context for any session

> Read this before touching the code. Last updated: 2026-10-14.

## What this project is

**SiteSentinel** — a public web app where anyone pastes a URL and receives an executive
website QA report. Four headless agents (Capture, Audit, Guard, Intel) run five stages
against one page and produce an A4 PDF plus structured JSON.

## Current state

* Engine, web app, report and frontend are complete and verified end to end.
* `python -m pytest` → 21 passed. Full coverage for robots fail-closed, static proof of no submit path, URL guard & SSRF protection, LLM JSON extraction, report determinism, and configuration integrity.
* Engine hardened with configurable concurrent scan limiting (`SITESENTINEL_MAX_CONCURRENT=3`), task retention to prevent GC, cached environment loading, and tuned stage timeouts.
* Website frontend completely redesigned into a dark engineering-lab diagnostic instrument with responsive lightbox, animated live counters, findings severity filter, and full ARIA accessibility.
* `python scripts/verify_e2e.py` exercises the complete live flow against `tests/fixture_site`.
* Legacy Era-1/Era-2 code remains deleted. `main` / `polish/premium-redesign` contains the unified product.
* Deployment is prepared: engine → Cloud Run (`Dockerfile`), UI → Vercel (`vercel.json` + `scripts/build-vercel.mjs`). See [DEPLOYMENT](DEPLOYMENT.md).

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
