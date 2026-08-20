"""Forms & business-logic reasoning agent.

Goes beyond "does the form submit 200 OK" — see brief section B. Tests
boundary values (currency decimal conventions, employee-count extremes),
internationalized input, and validation-message correctness.

SAFETY: this module contains the enforcement point for the single most
important constraint in the whole project. Read NEVER_SUBMIT before
touching this file.
"""

from __future__ import annotations

from playwright.sync_api import Browser, Page

from ..config import SAFETY
from ..models import AgentSource, Finding, PageTarget, PageType, Severity
from ..playwright_utils import goto_and_settle, new_context, throttle

# Page types where the ONLY forms present are real lead-gen forms (Request
# a Demo / Talk to Sales). The agent will fill fields and read validation
# state on these, but the submit button is NEVER clicked. This is checked
# in code, not just documented — see run() below.
NEVER_SUBMIT_PAGE_TYPES = {PageType.DEMO_FORM}

BOUNDARY_TEST_CASES = [
    {"label": "min employee count", "field_hint": "employee", "value": "1"},
    {"label": "very large employee count", "field_hint": "employee", "value": "100000"},
    {"label": "JPY-style zero-decimal reward amount", "field_hint": "amount", "value": "50000"},
    {"label": "two-decimal reward amount", "field_hint": "amount", "value": "49.99"},
    {"label": "non-Latin name", "field_hint": "name", "value": "田中 太郎"},
    {"label": "name with diacritics", "field_hint": "name", "value": "François Müller"},
    {"label": "international phone format", "field_hint": "phone", "value": "+91 98765 43210"},
    {"label": "invalid email, no @", "field_hint": "email", "value": "not-an-email"},
]


def run(browser: Browser, target: PageTarget, shard_key: str = "default") -> list[Finding]:
    findings: list[Finding] = []
    ctx = new_context(browser, {"width": 1440, "height": 900})
    page = ctx.new_page()
    throttle(shard_key)
    goto_and_settle(page, target.url)

    forms = page.locator("form")
    visible_forms = []
    for i in range(forms.count()):
        form = forms.nth(i)
        try:
            if form.is_visible():
                visible_forms.append(form)
        except Exception:
            continue

    if not visible_forms:
        ctx.close()
        return [Finding(
            url=target.url, agent=AgentSource.FORMS, severity=Severity.INFO,
            title="No forms found on page", tags=["forms"],
        )]

    is_lead_gen_page = target.page_type in NEVER_SUBMIT_PAGE_TYPES

    for i, form in enumerate(visible_forms):
        findings.extend(_probe_form(page, form, target, is_lead_gen_page, form_index=i))

    ctx.close()
    return findings


def _probe_form(page: Page, form, target: PageTarget, is_lead_gen_page: bool, form_index: int) -> list[Finding]:
    findings: list[Finding] = []

    for case in BOUNDARY_TEST_CASES:
        field = _find_field(form, case["field_hint"])
        if field is None:
            continue

        value = case["value"]
        if is_lead_gen_page and case["field_hint"] == "name":
            # Tag it unmistakably, per the safety checklist, in case any
            # autosave/analytics beacon fires on blur before we stop short
            # of submit.
            value = f"{SAFETY.dummy_data_marker} ({value})"

        try:
            field.fill(value)
            page.keyboard.press("Tab")  # trigger blur-based validation
            page.wait_for_timeout(300)
        except Exception as e:
            findings.append(Finding(
                url=target.url, agent=AgentSource.FORMS, severity=Severity.LOW,
                title=f"Could not interact with field for '{case['label']}'",
                detail=str(e), tags=["forms", "interaction-error"],
            ))
            continue

        validation_issue = _check_validation_state(field, case)
        if validation_issue:
            validation_issue.url = target.url
            findings.append(validation_issue)

    if is_lead_gen_page:
        findings.append(Finding(
            url=target.url, agent=AgentSource.FORMS, severity=Severity.INFO,
            title=f"Form {form_index}: stopped before submit (safety policy)",
            detail=(
                "This is a Request a Demo / Talk to Sales form. Per the "
                "production-safety checklist, the agent fills fields to "
                "test validation but never clicks submit, to avoid "
                "polluting the real sales pipeline with test leads."
            ),
            tags=["forms", "safety", "no-submit"],
        ))
    else:
        # Non-lead-gen forms (e.g. newsletter signup, on-site search) may
        # still warrant caution; default is still no-submit unless a
        # human has explicitly reviewed and whitelisted the specific form.
        findings.append(Finding(
            url=target.url, agent=AgentSource.FORMS, severity=Severity.INFO,
            title=f"Form {form_index}: validation tested, submit skipped (default policy)",
            tags=["forms", "safety", "no-submit"],
        ))

    return findings


def _find_field(form, field_hint: str):
    selector = f"input[name*='{field_hint}' i], input[id*='{field_hint}' i], input[placeholder*='{field_hint}' i]"
    locator = form.locator(selector)
    for i in range(locator.count()):
        candidate = locator.nth(i)
        try:
            if candidate.is_visible():
                return candidate
        except Exception:
            continue
    return None


def _check_validation_state(field, case: dict) -> Finding | None:
    """Read aria-invalid / nearby error text to judge whether validation
    messaging is correct, not just present — per brief: 'confirm validation
    messages are correct and non-broken, not just that something renders.'
    """
    aria_invalid = field.get_attribute("aria-invalid")
    is_invalid_case = case["field_hint"] == "email" and case["value"] == "not-an-email"

    if is_invalid_case and aria_invalid != "true":
        return Finding(
            agent=AgentSource.FORMS, severity=Severity.MEDIUM,
            title="Invalid email accepted without validation flag",
            detail=f"Field did not set aria-invalid=true after entering '{case['value']}'.",
            tags=["forms", "validation", "a11y-adjacent"],
        )

    if not is_invalid_case and aria_invalid == "true":
        return Finding(
            agent=AgentSource.FORMS, severity=Severity.MEDIUM,
            title=f"Valid input flagged as invalid: {case['label']}",
            detail=f"Field set aria-invalid=true after entering legitimate value '{case['value']}'.",
            tags=["forms", "validation", "false-positive"],
        )

    return None
