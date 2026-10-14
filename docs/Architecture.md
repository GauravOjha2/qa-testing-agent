# Architecture — SiteSentinel

## Deployment topology

The scanner needs a real Chromium, the Lighthouse CLI, a writable artifact directory and a
multi-minute budget. None of that fits a serverless function, so the system is split:

```
        ┌──────────────────────────────┐        ┌───────────────────────────────────┐
        │  UI  (static, no framework)  │  HTTPS │  Engine  (container, Cloud Run)   │
        │  Vercel or served by engine  │───────►│  FastAPI + Playwright + Chrome    │
        │  index.html app.css app.js   │  SSE   │  Lighthouse CLI · axe-core        │
        └──────────────────────────────┘        └────────────────┬──────────────────┘
                                                                 │ JSON mode
                                                                 ▼
                                                    ┌────────────────────────┐
                                                    │ gemini-flash-latest    │
                                                    └────────────────────────┘
```

The UI talks to the engine over `window.SENTINEL_API` (written at build time into
`static/app-config.js`). Empty means same-origin, which is what you get when the engine
serves the UI itself. Cross-origin access is allowed by `CORSMiddleware` and locked down
with `SITESENTINEL_ALLOWED_ORIGINS`.

The progress stream is deliberately a **direct** browser → engine SSE connection rather
than a proxy through a serverless function, so a 2–3 minute scan never hits a function
timeout or a proxy buffer.

## Request flow

```
POST /api/scan ──► validate (scheme, host, SSRF) ──► JobStore.create
                                                       │
                                    asyncio.create_task(_drive(job))
                                                       │
GET /api/scan/{id}/events ◄── SSE ◄──── job.emit(event)  (replay history, then live)
                                                       │
GET /api/scan/{id}/report.pdf ◄── FileResponse ◄── runs/<id>/report.pdf
```

## Components

| Module | Responsibility |
|---|---|
| `server.py` | routes, URL validation + SSRF guard, CORS, SSE endpoint, artifact serving, static UI mount |
| `app/engine.py` | the orchestrator: pre-flight robots check, stage order, per-stage timeout + isolation, dedup, artifact writing |
| `app/jobs.py` | in-process job registry, event history, listener fan-out, TTL sweep of `runs/` |
| `app/stages/*` | the four agents' five stages (see below) |
| `app/report.py` | builds the A4 HTML and prints it to PDF with headless Chromium |
| `app/synthesis.py` | executive summary + top risks, with a deterministic fallback |
| `app/llm.py` | the only AI client in the codebase: `gemini-flash-latest`, JSON mode, retries |
| `app/robots.py`, `app/ratelimit.py` | permission and politeness primitives |

## Stage contracts

Every stage is `async (browser, url, …) -> list[Finding]` and is wrapped by the engine in
`asyncio.wait_for` with a per-stage budget. A stage that raises is recorded as `failed`
with its exception text and the scan continues — a partial honest report beats a hard
error. Statuses emitted to the UI: `ok`, `degraded` (worked, but via a fallback), `failed`.

| Stage | Key | Notes |
|---|---|---|
| Captures + overflow | `screenshots` | one context per viewport, lazy-load scroll pass, `scrollWidth - innerWidth` probe, Pillow thumbnail generation |
| Accessibility | `accessibility` | axe-core injected from `node_modules/axe-core/axe.min.js`, `wcag2a/aa`, `wcag21a/aa`, `wcag22aa`; axe `impact` → severity |
| Core Web Vitals | `vitals` | Lighthouse CLI (mobile form factor) parsed for LCP/CLS/TBT/FCP/score; falls back to a `PerformanceObserver` lab measurement → `degraded` |
| Form safety | `forms` | three guardrail layers, per-field boundary/invalid/i18n probes, reads `checkValidity()` / `validationMessage` / `aria-invalid` |
| AI answer check | `ai` | ground-truth scrape (title, meta, headings, JSON-LD, CTAs, price strings, body copy) + desktop screenshot → one multimodal call; also produces visual-review findings |

## Data model

```
Finding   id (sha1 of category+rule+selector) · category · severity · title · detail
          evidence{} · recommendation
ScanResult scan_id · target_url · final_url · scanned_at · elapsed_seconds
          user_agent · model · severity_counts · findings[] · top_risks[]
          executive_summary · screenshots[] · vitals{} · stages[] · safety{}
```

`severity_counts` is derived from `findings`, never stored separately, so the KPI cards and
the finding list cannot drift. `report.json` is a straight serialization of `ScanResult`;
`report.pdf` is rendered from the same object.

## Severity mapping

| Source | Rule |
|---|---|
| axe-core | `critical → critical`, `serious → high`, `moderate → medium`, `minor → low` |
| Overflow | > 40px → `high`, otherwise `medium` |
| Core Web Vitals | beyond the "poor" threshold → `critical`, beyond "good" → `high` |
| Forms | invalid input accepted with no feedback → `high`; unannounced error → `medium`; unbounded text field → `low` |
| GEO/AEO | unanswerable buyer question → `high` for pricing, else `medium`; wrong-claim risk → model-assigned |
| Visual review | model-assigned, default `medium` |

## Concurrency and isolation

* One browser per scan; one context per stage/viewport, always closed in a `finally`.
* A single `RateLimiter` instance per scan serialises every request to the target origin.
* Jobs are in-process, which makes a single instance the simplest topology. For multiple
  instances, back `JobStore` with Redis or Firestore and move `runs/` to a bucket — the
  `emit`/`stream` interface is the only thing that needs to change.

## Failure behaviour

| Failure | Result |
|---|---|
| robots.txt unreachable / 5xx / disallow | scan refused with a specific reason shown in the UI |
| A stage raises or times out | that stage reports `failed`; the rest of the scan completes |
| Lighthouse missing | `vitals` reports `degraded`, observer numbers used and labelled |
| `GEMINI_API_KEY` absent | `ai` reports `degraded` with an "AI layer disabled" finding |
| Model call fails mid-scan | synthesis falls back to a deterministic summary |
| SSE drops mid-scan | client polls `GET /api/scan/{id}` once and recovers the finished result |
