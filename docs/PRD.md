# PRD — SiteSentinel

## Problem

A marketing or product page can be *up* and still be losing money. Uptime pings, link
crawlers and HTML validators cannot see the four classes of defect that actually cost a
B2B SaaS business:

1. **Broken experience at some viewport** — content scrolls sideways on a phone, a hero
   collapses on a tablet. Nobody notices because everyone reviews on a laptop.
2. **Silent form failure** — a lead form accepts `not-an-email`, or rejects a legitimate
   international name, and the visitor quietly leaves. Nobody finds out until pipeline
   misses appear a quarter later.
3. **Accessibility debt** — unlabelled inputs, missing alt text, failing contrast. This
   blocks real users, invites WCAG/ADA complaints, and is invisible to the team that
   built the page.
4. **Answer-engine invisibility** — buyers now ask an AI "what does this cost / who is it
   for". If the page never states those facts, the answer engine guesses, and the guess
   becomes the buyer's truth.

Existing tools cover fragments of this (axe in devtools, Lighthouse in CI, a screenshot
service) but nothing hands a non-engineer one prioritised document they can forward.

## Users

| User | Wants | Success looks like |
|---|---|---|
| Founder / PM | "Is my page actually OK?" | A one-page verdict and a short risk list they understand |
| Growth / SEO owner | "Why don't AI answers cite us?" | Concrete missing facts and the fix, in buyer language |
| Engineer receiving the report | Reproduce the bug fast | Selector, snippet, failing rule, expected fix |
| Agency / consultant | Repeatable client deliverable | PDF + JSON for the same price of a URL paste |

## Jobs to be done

* Paste a URL, wait ~2–3 minutes, receive a report. No account, no install, no CLI.
* Trust that the scan was polite and non-destructive — this runs against *other people's*
  production sites.
* Show the evidence, not just the verdict: screenshots, selectors, measured numbers.
* Get the same answer twice. A flaky scanner is a toy.

## Scope — v1 (shipped)

**In:** landing → live progress → results → PDF/JSON download. Five stages across four
agents (captures, accessibility, Core Web Vitals, form safety, AI-answer readiness).
Severity model, dedup, deterministic finding IDs. Fail-closed robots.txt. Honest
User-Agent. 1.5s throttle. SSRF guard. No-submit guardrail in three layers. All AI on
`gemini-flash-latest`.

**Out (deliberately):** multi-page crawling and site maps, authenticated flows, PDF/DOCX
targets, historical diffing between scans, scheduled recurring scans, accounts/teams,
long-term artifact storage, JS-bundle or dependency-vulnerability analysis.

## Requirements

| # | Requirement | How it is met |
|---|---|---|
| R1 | Any public URL, no install | FastAPI + static SPA, one input |
| R2 | Visible progress, honest failure | SSE stage events; a failed stage reports `failed`, never silently passes |
| R3 | Evidence for every finding | Selector + snippet + measured value + embedded capture |
| R4 | Non-destructive by construction | No submit path (AST-tested), non-GET requests aborted, read-only browsing |
| R5 | Permission before access | robots.txt fetched first, fail-closed |
| R6 | Executive-legible output | A4 PDF: cover, KPI cards, summary, risks, evidence, safety statement |
| R7 | Machine-legible output | `report.json` rendered from the same result object |
| R8 | Reproducible | Deterministic finding IDs, dedup, stable sort |
| R9 | One model policy | `gemini-flash-latest` for every AI layer, one key |
| R10 | Deployable | Container for the engine, static bundle for the UI |

## Non-functional targets

* Scan completes in ~1–3 minutes on a normal marketing page.
* UI: responsive from 360px, keyboard operable, `aria-live` progress, reduced-motion safe.
* Report: A4, print-safe colours, multi-page with no orphaned cards.
* Engine: per-stage timeouts so one slow stage cannot hang a scan.

## Success signals

* A scan of the bundled fixture produces findings across all four agents.
* `scripts/verify_e2e.py` passes end to end, including `forms_submitted == 0`.
* A stakeholder can act on the PDF without asking an engineer what a finding means.
