# Rules — boundaries for any AI working on this repo

Applies to the ADK pipeline on `main`. The frozen `procedural-pipeline`
branch is reference-only; these rules govern how `main` evolves.

## Hard safety rules (never violate)

1. **NEVER complete a real form submission.** Submission is impossible by
   construction, twice over: `prevent_form_submit_guardrail`
   (`agents.py`, a `before_tool_callback` matching submit intent across tool
   name + arguments, escape-normalized) and the tool policy in
   `tools.py::test_form_boundaries` (fills fields, reads `aria-invalid`,
   never touches submit). Do not weaken either layer, do not "temporarily"
   bypass the guardrail, do not write a test that submits.
2. **Respect robots.txt, fail closed.** Every tool call re-checks via
   `_gate()` → `crawler.check_robots_allowed`; unreachable robots.txt aborts
   the call. Never flip this default to allow.
3. **Keep the throttle.** `SAFETY.min_delay_seconds = 1.5` between page loads.
   Do not parallelize page loads, do not lower the delay.
4. **Honest identification.** The contactable User-Agent stays. Never spoof a
   normal browser UA.
5. **Tag all test data.** Values that could reach a backend get the
   `QA-Agent-Test — please disregard` marker prefix.
6. **Secrets never enter git.** `.env` is gitignored. Never hardcode API keys,
   never echo key values into logs/findings/reports. Artifacts
   (`local_findings_adk/`, `screenshots/`, `*.pdf`) are gitignored too —
   regenerate, don't commit.

## Honesty rules

7. **No fabricated findings.** If a check didn't run (blocked load, missing
   key, tool error), the finding/status says so. Tool payloads carry real
   status fields; the aggregator trusts them.
8. **Trust tools, not prose.** The structured log is built from harvested
   function responses, never from the supervisor's narrative. Keep it that way.
9. **Coverage claims must match execution.** Pass findings record which layers
   actually ran; the PDF safety footer states exactly what was done to the site.
10. **Verify before reporting.** Surprising findings (e.g. a deprecated
    `<blink>` tag) get confirmed against the live DOM before entering a report.

## Library & code rules

11. Model calls are defined declaratively in `agents.py` (LlmAgent + model +
    GenerateContentConfig); no ad-hoc SDK generation calls sprinkled in tools.
    `google.genai.types` is config-only.
12. Browser work goes through `xoxoday_qa/playwright_utils.py` helpers
    (`throttle`, `goto_and_settle`, `PageMonitor`, breakpoint capture) so
    safety logic exists once.
13. **Sync Playwright never runs inside the asyncio loop.** Tools wrap
    blocking implementations in `asyncio.to_thread`.
14. ADK contracts are exact: guardrail callbacks accept `tool_context=` (that
    kwarg name matters); Agents reject unknown constructor fields; instruction
    `{placeholders}` must exist in session state or seeding fails.
15. Specialists end with `transfer_to_agent(qa_supervisor_agent)`; supervisor
    and specialists stay at temperature=0 for deterministic orchestration.
16. New Python deps need a reason in the PR/commit; prefer stdlib. Node deps:
    axe-core only (package.json).
17. One failing tool never kills the run: tools catch their own exceptions and
    return structured error payloads the aggregator records honestly.
18. Type hints throughout; comments explain *why*, not *what*.

## What an AI should NOT do here

- Re-introduce cloud/GCP code (removed deliberately; see Phases.md/Memory.md).
- Merge or cherry-pick from `procedural-pipeline` onto `main`.
- Blind `git add -A` — review staged files (legacy copies exist locally,
  excluded via `.git/info/exclude`, but exclusions are not a substitute for
  review).
- Embed multi-page-tall screenshots raw in the PDF; route through
  `slice_screenshot()` (black-band glitch).
- Widen crawler `_TYPE_HINTS` regexes without adding a classification test.
- Drop the raw findings appendix when touching `generate_pdf.py` severity
  ordering/colors.
- Rewrite working modules wholesale; make surgical changes and run
  `py -m pytest tests/ -q`.

## Definition of done for any change

Tests pass (currently 9) → run the single-page demo end-to-end
(`py adk_qa_pipeline\main.py --url …`) → inspect the newest
`local_findings_adk/adk_run_*.json` → regenerate the PDF if user-facing
(`py adk_qa_pipeline\generate_pdf.py`) → committed with a message that says why.
