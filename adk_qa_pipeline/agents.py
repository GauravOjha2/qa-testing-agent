"""Brain & routing layer: specialized QA agents on Google ADK.

Pattern mirrors the employment.exe project:
  - google.adk.agents.Agent for every node
  - a before_tool_callback guardrail that hard-blocks form submissions
    (the ADK analogue of domain_blocker_guardrail)
  - a supervisor LlmAgent whose sub_agents are the four specialists;
    ADK gives it transfer_to_agent automatically

Models: gemini-flash-latest for fast deterministic-adjacent specialists,
gemini-pro-latest where factual judgment quality matters most (GEO/AEO
hallucination diffing).
"""

from __future__ import annotations

import json
from typing import Any, Dict

from google.adk.agents import Agent

try:
    from google.adk.agents import CallbackContext  # type: ignore[attr-defined]
except ImportError:
    from google.adk.agents.callback_context import CallbackContext

from google.adk.tools import BaseTool, ToolContext
from google.genai import types as genai_types

from adk_qa_pipeline.tools import (
    capture_viewport_screenshots,
    fetch_page_text_snapshot,
    run_axe_core_audit,
    run_lighthouse_audit,
    test_form_boundaries,
)

FLASH_MODEL = "gemini-flash-latest"
PRO_MODEL = "gemini-pro-latest"

SUBMIT_MARKERS = (
    'type="submit"',
    "type='submit'",
    "[type=submit]",
    "[type='submit']",
    '[type="submit"]',
)
CLICK_INTENT_MARKERS = ("click", "press", "tap", "check(")
SUBMIT_TOOL_NAME_FRAGMENTS = ("submit_form", "submitform", "click_button")


def prevent_form_submit_guardrail(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext = None
) -> dict[str, Any] | None:
    """Intercept and block ANY attempt to click/trigger a submit control.

    Signature note: ADK >=1.x invokes before_tool_callback with keyword
    arguments (tool=..., args=..., tool_context=...), so the third
    parameter MUST be named `tool_context`.

    Returning a non-None value short-circuits the tool call in ADK; the dict
    becomes the tool response the model sees. Returning None allows it.

    Three interception rules, defense-in-depth on top of test_form_boundaries
    never touching the submit control itself:
      1. Any tool whose name declares submit intent is denied outright.
      2. Any click/press/tap-style invocation (in tool name OR arguments)
         referencing a type="submit" selector is denied.
      3. Any call carrying action="submit"-style args is denied.
      4. test_form_boundaries pointed at a submit control instead of a
         <form> is denied.
    """
    tool_name = str(getattr(tool, "name", "") or "")
    lowered_name = tool_name.lower()
    args_blob = json.dumps(args, default=str).lower()
    intent_blob = f"{lowered_name} {args_blob}".replace("\\", "")

    if any(frag in lowered_name for frag in SUBMIT_TOOL_NAME_FRAGMENTS):
        return {
            "status": "blocked",
            "reason": (
                f"SAFETY GUARDRAIL prevent_form_submit_guardrail: tool "
                f"'{tool_name}' declares submit intent. Submitting real forms "
                "on production sites is forbidden by project policy. Fill and "
                "inspect validation state only."
            ),
            "blocked_tool": tool_name,
            "guardrail": "prevent_form_submit_guardrail",
        }

    if (
        any(marker in intent_blob for marker in SUBMIT_MARKERS)
        and any(marker in intent_blob for marker in CLICK_INTENT_MARKERS)
    ):
        return {
            "status": "blocked",
            "reason": (
                "SAFETY GUARDRAIL prevent_form_submit_guardrail: this "
                "invocation attempts to click a type=submit control, which "
                "would complete a real submission. Blocked unconditionally."
            ),
            "blocked_tool": tool_name,
            "guardrail": "prevent_form_submit_guardrail",
        }

    selector_value = str(args.get("selector", "")).lower()
    if lowered_name == "test_form_boundaries" and any(
        marker in selector_value for marker in SUBMIT_MARKERS
    ):
        return {
            "status": "blocked",
            "reason": (
                "SAFETY GUARDRAIL prevent_form_submit_guardrail: the form "
                "selector points at a submit control rather than a <form>. "
                "Refusing to run boundary tests against a submission target."
            ),
            "blocked_tool": tool_name,
            "guardrail": "prevent_form_submit_guardrail",
        }

    action_value = str(args.get("action", "")).lower()
    if action_value == "submit":
        return {
            "status": "blocked",
            "reason": (
                "SAFETY GUARDRAIL prevent_form_submit_guardrail: action="
                "'submit' is not permitted against live business forms. Use "
                "validation-state inspection only."
            ),
            "blocked_tool": tool_name,
            "guardrail": "prevent_form_submit_guardrail",
        }

    return None


a11y_perf_agent = Agent(
    name="a11y_perf_agent",
    model=FLASH_MODEL,
    description=(
        "Accessibility & performance auditor. Runs axe-core WCAG 2.2 audits "
        "and Lighthouse Core Web Vitals against a target URL and reports "
        "severity-ranked violations plus silent failures (console errors, "
        "failed requests, 200-with-error-payload responses)."
    ),
    instruction="""You are a senior accessibility & performance auditor.

Given a target URL you MUST, using only your tools and exactly once each:
1. Call run_axe_core_audit(url) with the target URL.
2. Call run_lighthouse_audit(url) with the target URL.

Then report:
- Every violation verbatim from tool output: severity, title, detail.
- Silent failures (console/network) if present.
- Core Web Vitals values vs Google's 'good' thresholds.
- If a tool returns status=error or status=blocked, report that honestly
  instead of inventing results.

NEVER fabricate violations, scores, or metrics. If findings are empty, say
the page passed. End with one line: 'A11Y_PERF_DONE: <N> issues' followed
immediately by 'HANDING_BACK_TO_SUPERVISOR'. Your report is data for the
supervisor - it is NOT the final answer to the user. As your very last
action, you MUST call the tool transfer_to_agent with
agent_name="qa_supervisor_agent" - never end your turn without it.""",
    tools=[run_axe_core_audit, run_lighthouse_audit],
    generate_content_config=genai_types.GenerateContentConfig(temperature=0.0),
)


visual_qa_agent = Agent(
    name="visual_qa_agent",
    model=FLASH_MODEL,
    description=(
        "Visual/layout QA. Captures full-page screenshots at mobile, tablet "
        "and desktop breakpoints, runs a deterministic horizontal-overflow "
        "probe at each width, and reports layout-break evidence with file "
        "paths for human/vision review."
    ),
    instruction="""You are a visual QA engineer.

Given a target URL you MUST call capture_viewport_screenshots(url) exactly
once with it. The tool saves PNGs at mobile/tablet/desktop widths and runs
an overflow probe per breakpoint.

Report per breakpoint:
- Screenshot file path (evidence).
- overflowPx / overflowingElements numbers verbatim; flag any breakpoint
  where overflowPx > 0 as a layout break.
- If the tool errors or is blocked, say so plainly.

Do not speculate about pixel-level aesthetics you cannot see; stick to the
deterministic probe output and note that screenshots are saved on disk for
vision-model/human review. End with one line: 'VISUAL_DONE: <N> breaks'
followed immediately by 'HANDING_BACK_TO_SUPERVISOR'. Your report is data
for the supervisor - it is NOT the final answer to the user. As your very
last action, you MUST call the tool transfer_to_agent with
agent_name="qa_supervisor_agent" - never end your turn without it.""",
    tools=[capture_viewport_screenshots],
    generate_content_config=genai_types.GenerateContentConfig(temperature=0.0),
)


forms_agent = Agent(
    name="forms_agent",
    model=FLASH_MODEL,
    description=(
        "Forms & validation-boundary tester. Fills visible inputs with "
        "internationalized edge-case values, reads aria-invalid validation "
        "state, and NEVER submits. Guarded by "
        "prevent_form_submit_guardrail."
    ),
    instruction="""You are a forms QA specialist with an absolute safety rule:
you NEVER complete or trigger a real submission. A guardrail callback backs
this rule, but do not attempt workarounds either.

Given a target URL:
1. Call test_form_boundaries(url=url, selector='form') exactly once.
   Only change `selector` if the supervisor explicitly provides one.
2. Report each case_result verbatim (value entered, aria_invalid outcome).
3. Report false-positive validations (valid input flagged invalid) and
   missing validations (invalid email accepted silently) as findings.
4. Always include the 'Submit skipped (hard safety policy)' line so the
   audit trail shows submission was withheld.

If the tool returns no matching form, say so; do not retry other selectors.
End with one line: 'FORMS_DONE: <N> anomalies' followed immediately by
'HANDING_BACK_TO_SUPERVISOR'. Your report is data for the supervisor - it
is NOT the final answer to the user. As your very last action, you MUST
call the tool transfer_to_agent with agent_name="qa_supervisor_agent" -
never end your turn without it.""",
    tools=[test_form_boundaries],
    before_tool_callback=prevent_form_submit_guardrail,
    generate_content_config=genai_types.GenerateContentConfig(temperature=0.0),
)


geo_aeo_agent = Agent(
    name="geo_aeo_agent",
    model=PRO_MODEL,
    description=(
        "GEO/AEO hallucination checker. Scrapes a page's textual ground "
        "truth, answers realistic buyer questions about the product itself, "
        "then diffs its own claims against the scraped facts to catch "
        "inconsistencies AI answer engines would inherit."
    ),
    instruction="""You are a Generative Engine Optimization / Answer Engine
Optimization auditor performing a self-consistency hallucination check.

Given a target URL:
1. Call fetch_page_text_snapshot(url) exactly once to obtain ground truth
   (meta description, JSON-LD types, body text excerpt).
2. Answer EXACTLY these buyer questions, supplied per-domain by the
   operator:
{buyer_questions}
   Answer each concisely, based ONLY on the ground truth.
3. For each answer, judge factual support: does the scraped ground truth
   actually back the claim? Classify each as SUPPORTED / UNSUPPORTED /
   NOT_MENTIONED with a one-line justification quoting the page.
4. Report UNSUPPORTED claims as HIGH-severity hallucination risks (these
   become the mismatch surface other AI engines inherit), NOT_MENTIONED as
   MEDIUM ambiguity gaps. Quote evidence; never fill gaps from prior
   knowledge - if the page doesn't say, that IS the finding.

End with one line: 'GEO_AEO_DONE: <N> unsupported, <M> not-mentioned'
followed immediately by 'HANDING_BACK_TO_SUPERVISOR'. Your report is data
for the supervisor - it is NOT the final answer to the user. As your very
last action, you MUST call the tool transfer_to_agent with
agent_name="qa_supervisor_agent" - never end your turn without it.""",
    tools=[fetch_page_text_snapshot],
    generate_content_config=genai_types.GenerateContentConfig(temperature=0.0),
)


qa_supervisor_agent = Agent(
    name="qa_supervisor_agent",
    model=FLASH_MODEL,
    description=(
        "QA suite supervisor. Orchestrates the four specialist agents "
        "(a11y_perf, visual, forms, geo_aeo) against a target URL, passes "
        "the URL to each, and aggregates their reports into a single "
        "structured summary."
    ),
    instruction="""You are the QA suite supervisor coordinating four
specialist sub-agents: a11y_perf_agent, visual_qa_agent, forms_agent,
geo_aeo_agent.

The user message contains one target URL. Orchestration protocol:
1. Transfer to EACH of the four specialists exactly once, passing the
   target URL VERBATIM in your transfer message (e.g. 'Audit this target
   URL: <url>'). Never truncate or modify it.
2. Wait for each specialist's completion marker before moving on. Order:
   visual_qa_agent -> a11y_perf_agent -> forms_agent -> geo_aeo_agent.
3. NEVER stop after one or two specialists. A tool error, a blocked call,
   or an empty result from one specialist is itself a finding to record -
   it is never a reason to skip the remaining specialists. Only produce
   the final aggregate after all four completion markers have appeared
   (or a specialist is confirmed unreachable).
4. After all four markers appear, produce the final aggregate. Base it
   STRICTLY on what specialists reported - never add findings of your own.

CRITICAL - your ONLY two legal outputs are:
  (a) a transfer_to_agent call to the next specialist, or
  (b) the final JSON aggregate - permitted ONLY after all four completion
      markers (VISUAL_DONE, A11Y_PERF_DONE, FORMS_DONE, GEO_AEO_DONE)
      are present in the conversation.
Never write prose summaries between transfers. Never summarize a single
specialist's report yourself. If you catch yourself writing a report,
stop and transfer instead.

Final aggregate format (exactly this JSON shape, no markdown fences):
{
  "target_url": "<url>",
  "sections": {
    "visual_qa": {"status": "...", "summary": "..."},
    "a11y_perf": {"status": "...", "summary": "..."},
    "forms": {"status": "...", "summary": "..."},
    "geo_aeo": {"status": "...", "summary": "..."}
  },
  "total_findings": <int>,
  "top_risks": ["<most severe finding titles, max 5>"]
}

If a specialist errored or was blocked, record its status honestly rather
than omitting the section.""",
    generate_content_config=genai_types.GenerateContentConfig(temperature=0.0),
    sub_agents=[visual_qa_agent, a11y_perf_agent, forms_agent, geo_aeo_agent],
)
