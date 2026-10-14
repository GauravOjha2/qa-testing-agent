# Rules — boundaries for anyone (human or AI) working on this repo

## Hard safety rules — never violate

1. **Never create a code path that can submit a form.** No `submit()`, no
   `requestSubmit()`, no clicking a submit control, no pressing Enter inside a form. The
   Guard agent fills fields and reads the DOM's validation state; that is all.
   `tests/test_scanner_core.py::test_forms_stage_has_no_submit_call_path` parses the stage's
   AST and fails the suite if this regresses. Keep all three layers intact: the absent code
   path, the init-script stubs + capture-phase cancel, and `block_mutations=True` on the
   browser context.
2. **robots.txt is fail-closed.** Never "fall back to allow" on a timeout, DNS error or 5xx.
   Only a genuine 404 (or another 4xx meaning "no rules published") may allow a scan.
3. **Keep the User-Agent honest and contactable** (`app/config.py::USER_AGENT`). Never spoof
   a browser or a search engine.
4. **Keep the throttle.** `RateLimiter` spaces requests to the target origin by
   `THROTTLE_SECONDS` (1.5s). Do not add a request path that bypasses it.
5. **Keep the SSRF guard.** Non-HTTP schemes, loopback, private ranges, link-local and
   metadata hosts stay rejected. `SITESENTINEL_ALLOW_PRIVATE_TARGETS` is a dev/CI flag and
   must never be enabled in a public deployment.
6. **Do not exfiltrate scan data.** Findings stay on the scan host; nothing is posted to a
   third party. Report evidence must not contain host filesystem paths.

## AI layer rules

1. **`gemini-flash-latest` only.** Every AI layer (GEO/AEO review, visual review, executive
   synthesis) goes through `app/llm.py`. No Gemini Pro, no other provider, no silent model
   substitution. One `GEMINI_API_KEY` drives all of it.
2. **Degrade, never crash.** A missing key, a timeout or a malformed reply must leave a
   complete report: mark the stage `degraded`, add a labelled finding, and fall back to the
   deterministic summary.
3. **No invented facts.** Prompts must instruct the model to answer only from the scraped
   ground truth and to report a gap when the page does not state a fact.

## Engineering rules

1. **Findings are data.** Build them as `Finding` objects with deterministic IDs; never
   hand-write HTML for a finding.
2. **`report.json` and `report.pdf` come from the same `ScanResult`.** Never render a report
   from anything else.
3. **A failing stage is reported, not hidden.** Statuses are exactly `ok`, `degraded`,
   `failed`; the UI shows the engine's own reason text.
4. **Bound the work.** New stages need a timeout budget in `app/config.py`, and caps on how
   many elements/fields/rules they touch.
5. **No new frontend dependencies.** `static/` is plain HTML/CSS/JS with no build step;
   keep it that way.
6. **Every user-visible change keeps the four UI states intact** — loading, empty, degraded,
   error — plus `prefers-reduced-motion` and keyboard operability.
7. **Tests before claims.** `python -m pytest` for logic, `scripts/verify_e2e.py` for the
   flow. If you cannot run them, say so rather than asserting it works.
