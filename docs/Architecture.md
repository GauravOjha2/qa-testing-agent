# Architecture — Xoxoday QA Agent

## Pipeline flow

```
scripts/run_local_demo.py
  │
  ├─► crawler.py ──── sitemap / explicit URLs ──► classify() ──► [PageTarget]
  │
  ├─► per page, one shared Chromium session:
  │     visual_qa.py      screenshots @3 breakpoints → vision judge (rubric JSON)
  │     forms_agent.py    fill boundary/i18n values → read aria-invalid (NEVER submits)
  │     geo_aeo_agent.py  static: JSON-LD/meta vs rendered text
  │                       dynamic: buyer questions → LLM engines → diff judge
  │     a11y_perf_agent.py axe-core (local bundle) + Lighthouse CLI + PageMonitor
  │
  ├─► store.py ──── one JSON per page ──► local_findings/<url>.json
  │                 screenshots ────────► screenshots/local/<page>_<bp>.png
  │
  └─► synthesis_agent.py ── dedupe by (agent,title) → rank by severity → report.html

scripts/generate_report.py
  └─► load local_findings/ → classify signal vs noise → styled HTML → headless
      Chromium print-to-PDF with embedded base64 screenshots → Xoxoday-QA-Report.pdf
```

## Folder structure

```
src/xoxoday_qa/
  config.py            SafetyConfig + RunConfig; loads .env; single source of truth
  models.py            Finding / PageResult / PageTarget dataclasses, severity enums
  crawler.py           sitemap expansion, robots.txt (fail-closed), classification
  playwright_utils.py  throttle(), PageMonitor (console/network), browser_session(),
                       goto_and_settle(), screenshot_at_breakpoints()
  store.py             save_page_result() / load_all_results() — local JSON only
  dom_utils.py         meta-description reader (immediate DOM eval, no locator waits)
  agents/
    visual_qa.py       rubric prompt → vision model → Finding list; tags mock mode
    forms_agent.py     BOUNDARY_TEST_CASES, NEVER_SUBMIT_PAGE_TYPES enforcement
    geo_aeo_agent.py   _static_layer + _dynamic_layer(returns engines_used)
    a11y_perf_agent.py axe injection (local-first), CWV thresholds, silent failures
    synthesis_agent.py dedupe/rank/summarize/render_html_report
    llm_client.py      provider wrapper: Gemini/Claude/Perplexity + is_mock_mode()
scripts/
  run_local_demo.py    single-machine pipeline runner (CLI)
  generate_report.py   findings → founder PDF (signal/noise separation included)
tests/test_crawler.py  11 unit tests: classification, navigation, form helpers
docs/                  PRD, Architecture, Rules, Phases, Design, Memory
local_findings/        raw scan output (committed as evidence)
screenshots/local/     breakpoint captures (committed as evidence)
.env                   GEMINI_API_KEY — GITIGNORED, never commit
```

## Technical stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.13 | team-familiar, Playwright first-class support |
| Browser automation | Playwright (sync) | real Chromium, network/console interception |
| A11y | axe-core 4.10 (npm, injected locally) | no CDN dependency; site CSP can't block it |
| Perf | Lighthouse CLI via npx subprocess | Core Web Vitals without Node API plumbing |
| AI | Gemini (`gemini-flash-latest`) via `google-generativeai` | cheap tier; Claude/Perplexity optional, auto-skipped |
| Persistence | local JSON files | inspectable, diffable, zero infra |
| Report | HTML → PDF via Playwright `page.pdf()` | reuses installed Chromium; self-contained output |
| Tests | pytest | standard, fast |

## Key design decisions

- **Uniform Finding schema** (models.py): every agent emits the same shape so
  synthesis/report never care who produced a finding.
- **Severity mapping:** axe impact → severity (critical→CRITICAL … minor→LOW);
  unmapped impacts default MEDIUM.
- **Signal vs noise lives in generate_report.py**, not in the agents: raw
  findings stay complete in JSON; presentation-layer classification keeps the
  report readable while the appendix retains everything.
- **Mock mode is explicit:** `llm_client.is_mock_mode()`; vision/GEO pass
  findings carry `[MOCK MODE]` detail + `mock` tag so reports can't overstate.
- **Cloud removed deliberately:** earlier scaffolding had Cloud Run Jobs/Firestore;
  stripped in favor of single-machine sequential scanning. Stateless-per-page
  design means horizontal scale-out later is infrastructure work, not a rewrite.
