# Rules — boundaries for any AI working on this repo

## Hard safety rules (never violate)

1. **NEVER complete a real form submission.** `forms_agent.py` fills fields and
   reads validation state only. The code path that clicks submit on lead-gen
   forms must not exist. Do not add it, do not "temporarily" bypass
   `NEVER_SUBMIT_PAGE_TYPES`, do not write a test that submits.
2. **Respect robots.txt, fail closed.** If robots.txt is unreachable,
   everything is disallowed (`crawler.check_robots_allowed`). Never flip this
   default to allow.
3. **Keep the throttle.** `SAFETY.min_delay_seconds = 1.5` between page loads.
   Do not parallelize page loads, do not lower the delay, do not remove
   `throttle()` calls before `goto`.
4. **Honest identification.** The custom User-Agent string with contact email
   stays. Never spoof a normal browser UA.
5. **Tag all test data.** Values that could reach a backend get the
   `QA-Agent-Test — please disregard` marker prefix.
6. **Secrets never enter git.** `.env` is gitignored. Never hardcode API keys,
   never echo key values into logs/findings/reports, never commit screenshots
   of credentials.

## Honesty rules

7. **No fabricated findings.** If a check didn't run (no API key, missing npx,
   blocked CDN), the finding says so — mock/scan-error tags stay in place.
8. **Coverage claims must match execution.** Pass findings must record which
   layers actually ran (see geo_aeo pass detail pattern).
9. **Verify before reporting.** Surprising findings (e.g. a deprecated `<blink>`
   tag) get confirmed against the live DOM before entering a report.

## Library & code rules

10. LLM calls go through `agents/llm_client.py` only — no direct SDK imports in
    agents. Provider SDKs import lazily inside functions.
11. Browser work goes through `playwright_utils.py` helpers (`new_context`,
    `goto_and_settle`, `throttle`, `PageMonitor`) so safety logic exists once.
12. New Python deps need a reason in the PR/commit; prefer stdlib. Node deps:
    axe-core only (package.json).
13. Every agent's `run()` catches its own per-page exceptions and converts them
    to LOW-severity findings or PageResult.error — one bad page never kills the
    scan (see run_local_demo.py try/except).
14. Dataclasses + type hints for models; comments explain *why*, not *what*.

## What an AI should NOT do here

- Re-introduce cloud/GCP code (removed deliberately; see Memory.md).
- Widen `_TYPE_HINTS` regexes without adding a classification test.
- Edit `generate_report.py` severity buckets without keeping the raw appendix complete.
- Rewrite working modules wholesale; make surgical changes and run `py -m pytest tests/ -q`.

## Definition of done for any change

Tests pass (currently 11) → run the single-page demo command end-to-end →
findings JSON inspected → report regenerated if user-facing → committed with a
message that says why.
