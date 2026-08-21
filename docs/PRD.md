# PRD — Xoxoday QA Agent

## Problem

Static site checkers (uptime pings, link crawlers, HTML validators) cannot catch
four classes of defects that actually hurt a B2B SaaS business:

1. **Visual/brand breakage** — layout collapses at some viewport, localized text
   overflows its container, brand elements render wrong. Pixel-diff tools drown
   in false positives on marketing sites that change content daily.
2. **Form business-logic failures** — a lead-gen form that accepts garbage
   (invalid emails, absurd values) or rejects legitimate international input
   pollutes the sales pipeline silently.
3. **AI-answer mismatch (GEO/AEO)** — buyers increasingly ask ChatGPT/Gemini
   about products. If AI engines describe the product differently than the
   site does, pipeline leaks before the site is ever visited.
4. **Silent failures** — JS console errors, blocked scripts, 200-OK-with-error-payload
   responses. Nothing 404s, nothing visibly breaks, and a human clicking around
   will never notice.

## Target users

- **Xoxoday engineering** — actionable defect list with selectors and evidence.
- **Xoxoday marketing/growth** — the CSP-blocked-tracker and AI-mismatch findings
  are revenue-adjacent, not just code bugs.
- **The submitting engineer** — demonstrates judgment on an ambiguous, unscoped
  task touching someone else's production site.

## Scope

**In scope:** scanning public xoxoday.com web properties page-by-page with four
specialist checks, deduplicating results, and producing an executive-ready PDF
report with screenshot evidence.

**Out of scope:** load testing, authenticated-area scanning, exploiting any
vulnerability, automated exploitation/remediation, mobile-native apps.

## Functional requirements

| # | Requirement |
|---|---|
| F1 | Discover pages via sitemap or explicit URL list; classify each by page type |
| F2 | Screenshot every page at mobile/tablet/desktop and judge renders with a vision model against a bounded rubric |
| F3 | Probe forms with boundary/i18n values and read validation state **without ever submitting** |
| F4 | Diff JSON-LD/meta claims against rendered content; ask configured LLM engines buyer questions and diff answers against page ground truth |
| F5 | Run WCAG 2.2 AA automated audit (axe-core), Core Web Vitals (Lighthouse), and a console/network monitor per page |
| F6 | Persist raw findings as inspectable JSON; dedupe + rank across pages |
| F7 | Render a self-contained PDF report: exec summary, confirmed issues with plain-English context, manual-review items, evidence screenshots, methodology, limitations |

## Non-functional requirements

- **Safety first:** robots.txt compliance (fail-closed), 1.5s/request throttle,
  honest contactable User-Agent, tagged test data, never-complete-a-submission.
- **Honesty:** when a layer didn't run (no API key, tool unavailable), the
  findings say so explicitly. No overstated coverage.
- **Zero infrastructure:** full pipeline runs on one machine; no cloud account needed.
- **Cost ceiling:** one Gemini API key drives all AI layers; ~11 small calls/page.

## Success criteria

- Every finding in the report traces to something that actually executed.
- Findings reproduce across independent runs (validated: visual findings from
  two separate sessions matched).
- A non-engineer (founder) can read the PDF top-to-bottom without jargon.
