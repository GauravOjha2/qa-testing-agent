# Memory — living context for any AI session

> Read this before touching the code. Last updated: 2026-08-24.

## Project status

**ADK refactor complete & pushed.** Branch structure:
- `main` — Google ADK pipeline (`adk_qa_pipeline/`), docs updated for ADK.
- `procedural-pipeline` — frozen snapshot of the original raw-Python build
  (agents/store/synthesis/scripts). Frozen on purpose; never merge forward.
Repo: https://github.com/GauravOjha2/qa-testing-agent (public).

## Environment facts

- Windows 11, PowerShell 5.1. Python via `C:\Windows\py.exe` (3.13.2).
- Node/npx available (Lighthouse CLI installed globally); axe-core bundled in
  `node_modules/` via package.json — kept, because tools inject it locally.
- google-adk installed (LlmAgent, InMemoryRunner, before_tool_callback);
  Pillow installed (PDF screenshot slicing).
- **Secrets:** `.env` at repo root holds `GEMINI_API_KEY` (new Google format,
  starts `AQ.`). Gitignored, verified absent from both branches. Never print
  its contents.
- No Anthropic/Perplexity keys (user doesn't want to pay).

## Commands that work

```powershell
py -m pytest tests/ -q                                   # 9 tests
py adk_qa_pipeline\main.py --url "https://signup.xoxoday.in/plum-pricing/"
py adk_qa_pipeline\generate_pdf.py                       # renders newest adk_run_*.json
```

Run takes ~2–3 min per page. Artifacts land in `local_findings_adk/adk_run_*.json`;
PDF lands at repo root as `ADK-QA-Report_<slug>.pdf`. All three artifact
classes are gitignored — evidence is regenerated per run, not committed.

## Decisions already made (do not relitigate)

- Cloud/GCP code removed on purpose (twice: procedural era and again in the
  ADK refactor). Don't re-add.
- **Trust tools, not prose:** main.py aggregates ground-truth tool payloads
  harvested from the ADK event stream; the supervisor's prose is decorative.
- Supervisor + specialists run at temperature=0; specialists MUST end with
  `transfer_to_agent(qa_supervisor_agent)` (prose handbacks strand the run).
- Form submission is impossible by construction: guardrail callback (intent
  blob over tool name+args, escape-normalized) AND tool policy that never
  touches submit.
- Per-domain buyer questions live in `BUYER_QUESTIONS_BY_DOMAIN` (tools.py),
  injected via `{buyer_questions}` session-state templating. Adding a domain =
  adding a dict entry.
- CSP-blocked third-party trackers are reported as an observability insight,
  not product bugs.
- Legacy procedural files exist locally (restored from the branch for
  reference) but are blocked from staging by `.git/info/exclude`. Never use a
  blanket `git add -A` without reviewing the staged list.

## Verified findings (latest ADK runs, reproducible)

- **plum-pricing:** image-alt ×4 (critical), meta-viewport zoom disabled
  (critical), color-contrast cluster, `<blink>` tag confirmed live in DOM
  (hidden), LCP ≈ 14s headless, CSP-blocked trackers (Clarity/Bing/Marketo/GA…).
- **syynapse.vercel.app** (generalization proof): 1 high color-contrast,
  1 medium LCP, GEO/AEO: 0 unsupported claims but 3 ambiguity gaps
  (regions/pricing/support unstated), per-domain buyer questions injected.

## Known quirks / gotchas

- Site intermittently serves Vercel/Cloudflare bot challenges → tiny (~10KB)
  screenshots mean a blocked load; rerun. Honest UA usually gets through.
- **Sync Playwright cannot run inside the asyncio event loop.** Every ADK tool
  wraps its blocking implementation in `asyncio.to_thread`. Don't "simplify"
  this away.
- **before_tool_callback is invoked with keyword `tool_context=`** — the
  callback parameter must have that exact name or ADK raises TypeError.
- `bypass_state_injection` is NOT an Agent constructor field (pydantic
  rejects unknown fields); it's a return value of `canonical_instruction()`.
- Instruction braces: only `{identifier}` placeholders that exist in session
  state are substituted; a missing key raises KeyError; non-identifiers pass
  through safely. Audit any new instruction containing literal JSON braces.
- Tall screenshots printed to PDF black-band in Chromium's tiler → always go
  through `slice_screenshot()`; never embed a multi-page-tall `<img>` raw.
- PowerShell 5.1 mangles quotes in inline `py -c "..."` with nested quotes →
  write a temp `.py` script instead (use `%TEMP%\opencode`).
- `git push` stderr progress shows as "RemoteException" noise — pushes
  succeed; confirm via `git log`.
- First `.env` write once failed leaving a corrupted file; if PermissionError
  appears, delete, recreate with Set-Content, verify round-trip read.
- I (the assistant) cannot view images the user pastes — verify PNG/PDF
  content programmatically (Pillow pixel stats, pymupdf render).

## Current state of tree

`main`: `adk_qa_pipeline/`, `src/xoxoday_qa/` core, trimmed `tests/`,
`docs/`, README, requirements.txt. Working tree clean after docs update.
Local-only extras (gitignored or excluded): `local_findings*/`, `screenshots/`,
`*.pdf`, legacy procedural files, `node_modules/`.
