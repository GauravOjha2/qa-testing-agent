# Xoxoday QA Agent

An agent system that tests xoxoday.com across four dimensions a static
crawler can't: visual/brand rendering (via a vision-model judge, not
pixel-diff), form business-logic edge cases, whether AI answer engines
describe the product correctly, and silent failures (200-OK-with-error-payload,
blocked scripts, console errors) that don't show up as a 404 or a
screenshot difference.

Built for a take-home challenge from Xoxoday's co-founder. The actual
question being answered isn't "can this write Playwright scripts" — it's
what a reasonable engineer does with an ambiguous, unscoped problem
touching someone else's live production site. See §5.

## 1. What it checks

| Agent | What it catches | How |
|---|---|---|
| **Visual QA** (`agents/visual_qa.py`) | Broken layout, i18n text overflow (esp. German), brand inconsistency | Screenshot at 3 breakpoints → vision-model judge with a bounded rubric |
| **Forms** (`agents/forms_agent.py`) | Currency-decimal edge cases (JPY vs. others), employee-count extremes, non-Latin names, broken validation messages | Fills fields, reads `aria-invalid` + error state, **never clicks submit on real lead-gen forms** |
| **GEO/AEO** (`agents/geo_aeo_agent.py`) | JSON-LD/meta-tag mismatches with rendered content; LLMs giving wrong answers about Xoxoday's products | Static schema diff + live prompts to Gemini/Claude/Perplexity, diffed against page ground truth |
| **A11y + Perf + Silent failures** (`agents/a11y_perf_agent.py`) | WCAG 2.2 AA violations, Core Web Vitals regressions, JS console errors, blocked/broken third-party scripts | axe-core (bundled locally, injected in-page), Lighthouse CLI, a network/console monitor attached to every page load |

## 2. Architecture

Single-machine pipeline, no cloud infrastructure required:

```
scripts/run_local_demo.py
  → crawls sitemap (or takes an explicit URL list), classifies pages by type
  → runs all 4 specialist agents per page through one shared browser session
  → findings → ./local_findings/*.json, screenshots → ./screenshots/local/

synthesis_agent.py
  → dedupes recurring findings (shared-component bugs don't flood the report)
  → ranks by severity
  → renders report.html

scripts/generate_report.py
  → turns raw findings into a founder-ready PDF with embedded screenshot evidence
```

The scan is deliberately sequential and rate-limited (1.5s between page
loads) so it behaves like one polite visitor. The agent code is
stateless per page, so scaling out later (multiple machines or a job
queue) is an infrastructure change, not a rewrite.

**Why an agent instead of a deterministic Selenium/Cypress suite:** a
selector-based script breaks the moment a redesign changes a class name,
and can only check presence/absence. The vision judge in `visual_qa.py`
and the diff judge in `geo_aeo_agent.py` reason about whether a result is
*correct*, which is the actual capability gap being tested here.

## 3. Running it

```bash
pip install -r requirements.txt
playwright install chromium
npm install axe-core                      # bundled locally; no CDN dependency
export GEMINI_API_KEY=...                 # optional — omit to run in mock LLM mode
export ANTHROPIC_API_KEY=...              # optional
export QA_AGENT_CONTACT_EMAIL=you@company.com

# explicit URL list
python scripts/run_local_demo.py --urls https://www.xoxoday.com/ https://www.xoxoday.com/pricing/

# or crawl the sitemap and auto-select the 15-25 page representative subset
python scripts/run_local_demo.py --sitemap https://www.xoxoday.com/sitemap.xml --demo-subset

# build the founder-ready PDF report from whatever is in local_findings/
python scripts/generate_report.py --out Xoxoday-QA-Report.pdf
```

Without any LLM API key set, the vision/GEO calls return a clearly-labeled
mock response so you can verify the whole pipeline shape (crawl → agents →
dedupe → report) runs cleanly before spending API budget on a real pass.

Performance metrics require Node.js on PATH (`npx lighthouse` is invoked
per page); without it the rest of the scan still completes and the perf
section is reported as unavailable.

## 4. Execution plan used for the submitted results

Architected for all ~200 pages but executed against a representative
subset chosen by `crawler.select_demo_subset()` to guarantee coverage of:
homepage, pricing/ROI calculator, one product page (Empuls/Plum/Compass),
one industry landing page, one blog post, one localized (non-English)
page, and the demo-request form (validation only — see §5). The deep-dive
results in the submitted report are from the Plum pricing page
(`signup.xoxoday.in/plum-pricing`).

## 5. Production-safety checklist

This is the actual differentiator most people attempting this exercise
won't think about — running an untrusted agent against someone else's
live business has second-order effects a sandboxed coding exercise
doesn't.

- [x] **Respects `robots.txt`** — `crawler.check_robots_allowed()`, fails
      closed (disallows everything) if robots.txt is unreachable, rather
      than defaulting to allow.
- [x] **Rate-limited, honestly identified** — every request goes through
      `playwright_utils.throttle()` (1.5s/request by default) with a
      real, contactable User-Agent string (`config.py::SafetyConfig`), not
      a spoofed browser UA.
- [x] **Never completes real form submissions** — `forms_agent.py` fills
      fields and reads validation state but the code path that would call
      `.click()` on a submit button for a Request-a-Demo / Talk-to-Sales
      form does not exist in this codebase. It tests up to, not through,
      submission.
- [x] **Any test data is obviously tagged** — if a field value could ever
      reach a backend (e.g. an autosave-on-blur), it's prefixed with
      `"QA-Agent-Test — please disregard"` (`SafetyConfig.dummy_data_marker`).
- [x] **Disclosed explicitly, not buried** — stated up front in the report.

## 6. Project layout

```
src/xoxoday_qa/
  config.py              safety limits + run config, single source of truth
  models.py              Finding / PageResult / PageTarget schemas
  crawler.py             sitemap discovery, classification, robots.txt, subset selection
  playwright_utils.py    screenshot capture, rate limiting, console/network monitor
  store.py               local-JSON findings persistence
  dom_utils.py           small DOM-read helpers
  agents/
    visual_qa.py         vision-model rubric judge
    forms_agent.py       boundary values, i18n input, NEVER_SUBMIT enforcement
    geo_aeo_agent.py     schema diff + multi-LLM cross-check
    a11y_perf_agent.py   axe-core + Lighthouse + silent-failure monitor
    synthesis_agent.py   dedupe, rank, HTML report
    llm_client.py        provider wrapper, mock mode when no API key set
scripts/
  run_local_demo.py      single-machine pipeline runner
  generate_report.py     founder-ready PDF report generator
tests/test_crawler.py    unit tests for classification, navigation, forms helpers
```

## 7. Known limitations / what a follow-up pass would add

- Lighthouse via CLI subprocess is functional but slower than the
  Node Lighthouse API directly; fine at demo scale, worth revisiting
  for a full 200-page nightly run.
- The GEO/AEO "ground truth" is the page's own rendered text — good
  enough to catch clear mismatches, but doesn't fact-check the site
  itself against reality.
- axe-core catches WCAG *automatable* checks (~30-40% of WCAG 2.2 AA);
  it's not a substitute for a manual audit, and the report says so.
