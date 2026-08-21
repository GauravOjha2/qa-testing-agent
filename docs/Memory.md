# Memory — living context for any AI session

> Read this before touching the code. Last updated: 2026-08-21.

## Project status

**Complete & submitted.** All phases 1–6 done (see Phases.md). Repo:
https://github.com/GauravOjha2/qa-testing-agent (public, branch `main`).

## Environment facts

- Windows 11, PowerShell 5.1. Python via `C:\Windows\py.exe` (3.13.2).
- Node/npx available (Lighthouse 12.8.2 installed globally); axe-core in
  `node_modules/` via package.json.
- **Secrets:** `.env` at repo root holds `GEMINI_API_KEY` (new Google format,
  starts `AQ.`, ~53 chars — NOT the old `AIza` format; that's fine). `.env` is
  gitignored and verified absent from the remote. Never print its contents.
- No Anthropic/Perplexity keys (user doesn't want to pay). Engines auto-skip.
- User's own PDF is personalized by them; repo carries the generated
  `Xoxoday-QA-Report.pdf` via a `!Xoxoday-QA-Report.pdf` gitignore exception.

## Commands that work

```powershell
py -m pytest tests/ -q                                   # 11 tests
& 'C:\Windows\py.exe' scripts\run_local_demo.py --urls "https://signup.xoxoday.in/plum-pricing/" --report-out "report.html"
py scripts/generate_report.py --out Xoxoday-QA-Report.pdf
```

## Decisions already made (do not relitigate)

- Cloud/GCP code (Cloud Run Jobs, Firestore, deploy/, orchestrator.py) was
  **removed on purpose** — user isn't deploying. Don't re-add.
- Single-machine sequential scan, 1.5s throttle. Safety rules in Rules.md are hard.
- Signal-vs-noise classification lives in generate_report.py; raw findings JSON
  stays complete (appendix keeps everything).
- CSP-blocked third-party trackers (Clarity, Bing UET, Marketo, GA4/GAds,
  LinkedIn…) are reported as an observability insight, not product bugs.

## Verified findings on plum-pricing page (reproducible)

- axe: image-alt ×4 (critical), meta-viewport zoom disabled (critical),
  color-contrast ×14, object-alt ×6, link-name, link-in-text-block
- `<blink style="visibility:hidden"><sup>New</sup></blink>` confirmed live in
  left-column nav (hidden, so easy to miss in DevTools)
- LCP ≈ 11.5s headless vs 2.5s threshold
- Visual (real Gemini vision): cookie banner blocks mobile content; tablet
  Support/Redeem links above main nav; stray arrow under newsletter field
- GEO/AEO (real Gemini): 2 high mismatches — "countries we deliver to" and
  "AI assistant" answers not substantiated by page content

## Known quirks / gotchas

- Site intermittently serves Vercel/Cloudflare bot challenges → tiny (~10KB)
  screenshots mean a blocked load; rerun. Honest UA usually gets through.
- `google-generativeai` prints a FutureWarning (deprecated SDK) — benign;
  migration to `google-genai` is Phase 7.
- First `.env` write once failed leaving a corrupted unreadable file; if
  PermissionError appears on `.env`, delete, recreate with Set-Content, verify
  round-trip read in both PowerShell and Python.
- `git push` stderr progress text shows as PowerShell "RemoteException" noise —
  pushes actually succeed; confirm via `git log`/`gh api`.

## Current state of tree

Clean working tree expected after commits db1ee73 + docs commit. Evidence
committed intentionally: `local_findings/*.json`, `screenshots/local/plum-pricing_*.png`.
