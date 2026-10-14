"""Stage 4 — form validation safety check.

GUARDRAIL, ENFORCED IN THREE INDEPENDENT LAYERS:
  1. This module contains no call to submit(), requestSubmit(), or any
     submit-button click. There is no code path that can submit a form.
  2. An init script (installed before any page script runs) replaces
     HTMLFormElement.prototype.submit/requestSubmit with a no-op recorder
     and installs a capture-phase 'submit' listener that calls
     preventDefault() + stopImmediatePropagation().
  3. The browser context aborts every non-GET request, so even if a page
     script submitted programmatically, nothing leaves the machine.

We fill boundary / invalid / i18n values and then read the browser's own
validation state (checkValidity, validationMessage, :invalid).
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Browser

from .. import config
from ..models import Finding, finding_id
from ..ratelimit import RateLimiter
from .browser import goto_polite, new_context

_GUARDRAIL_JS = """() => {
  window.__submitAttempts = [];
  const block = (name) => { return function () {
    window.__submitAttempts.push(name + ':' + new Date().toISOString());
    return undefined;
  }; };
  HTMLFormElement.prototype.submit = block('submit');
  HTMLFormElement.prototype.requestSubmit = block('requestSubmit');
  document.addEventListener('submit', (e) => {
    e.preventDefault(); e.stopImmediatePropagation();
    window.__submitAttempts.push('submit-event');
  }, true);
  const blockNav = (e) => {
    const t = e.target;
    if (t && (t.type === 'submit' || (t.tagName === 'BUTTON' && !t.type))) {
      e.preventDefault(); e.stopImmediatePropagation();
      window.__submitAttempts.push('submit-button-click');
    }
  };
  document.addEventListener('click', blockNav, true);
}"""

# Boundary / invalid / i18n probe values per input type.
_PROBES: dict[str, list[tuple[str, str, str]]] = {
    "email": [("invalid", "not-an-email", "must reject malformed email"),
              ("i18n", "user+üñïçøde@exämple.com", "must accept internationalised email")],
    "url": [("invalid", "notaurl", "must reject malformed URL")],
    "number": [("invalid", "abc", "must reject non-numeric input"),
               ("boundary", "-1", "must state whether negatives are allowed")],
    "tel": [("invalid", "abcdefg", "must reject alphabetic phone numbers")],
    "date": [("invalid", "2026-02-30", "must reject impossible dates")],
}
_DEFAULT_PROBES = [
    ("boundary", "A" * 512, "512-char value — checks maxlength enforcement"),
    ("i18n", "こんにちは世界 — العربية — 😀 — Œ", "multi-script + emoji value"),
]

_ENUMERATE_JS = """(limits) => {
  const forms = Array.from(document.querySelectorAll('form')).slice(0, limits.forms);
  return forms.map((form, fi) => {
    const fields = Array.from(form.querySelectorAll('input, select, textarea'))
      .filter(el => !['submit','button','reset','image','hidden','file'].includes(el.type))
      .slice(0, limits.fields);
    return {
      index: fi,
      id: form.id || form.getAttribute('name') || `form-${fi}`,
      action: form.getAttribute('action') || '',
      noValidate: form.noValidate,
      fields: fields.map((el, i) => {
        el.setAttribute('data-ss-probe', `${fi}-${i}`);
        return {
          probe: `${fi}-${i}`,
          tag: el.tagName.toLowerCase(),
          type: el.type || el.tagName.toLowerCase(),
          name: el.getAttribute('name') || '',
          id: el.id || '',
          required: !!el.required,
          maxlength: el.getAttribute('maxlength'),
          pattern: el.getAttribute('pattern') || '',
          autocomplete: el.getAttribute('autocomplete') || '',
          ariaLabel: el.getAttribute('aria-label') || '',
          label: (() => {
            if (el.id) { const l = document.querySelector(`label[for="${el.id}"]`); if (l) return l.innerText.trim().slice(0,60); }
            const p = el.closest('label'); if (p) return p.innerText.trim().slice(0,60);
            return el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
          })(),
          options: el.tagName === 'SELECT' ? Array.from(el.options).slice(0, 8).map(o => o.value) : []
        };
      })
    };
  });
}"""

_FILL_AND_READ_JS = """({probe, value}) => {
  const el = document.querySelector(`[data-ss-probe="${probe}"]`);
  if (!el) return null;
  el.focus();
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype
              : el.tagName === 'SELECT'   ? HTMLSelectElement.prototype
              : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, value);
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  el.dispatchEvent(new Event('blur', {bubbles: true}));
  const invalid = el.matches(':invalid');
  return {
    valid: el.checkValidity(),
    invalidPseudo: invalid,
    message: el.validationMessage || '',
    ariaInvalid: el.getAttribute('aria-invalid') || '',
    ariaDescribedBy: el.getAttribute('aria-describedby') || '',
    liveText: (() => {
      const ids = (el.getAttribute('aria-describedby') || '').split(/\\s+/).filter(Boolean);
      return ids.map(id => (document.getElementById(id) || {}).innerText || '').join(' ').trim().slice(0, 200);
    })(),
    valueAccepted: el.value.slice(0, 80)
  };
}"""


async def run(browser: Browser, url: str, limiter: RateLimiter, log) -> list[Finding]:
    context = await new_context(
        browser, config.VIEWPORTS["desktop"], extra_init_script=_GUARDRAIL_JS, block_mutations=True
    )
    findings: list[Finding] = []
    try:
        page = await context.new_page()
        await goto_polite(page, url, limiter)
        await page.wait_for_timeout(1200)
        forms = await page.evaluate(
            _ENUMERATE_JS, {"forms": config.MAX_FORMS, "fields": config.MAX_FIELDS_PER_FORM}
        )
        log(f"found {len(forms)} form(s); filling probes — submission is impossible by design")

        probed = 0
        for form in forms:
            form_label = form["id"]
            if not form["fields"]:
                continue
            for field in form["fields"]:
                probes = _PROBES.get(field["type"], _DEFAULT_PROBES)
                for kind, value, intent in probes:
                    if field["type"] == "select" and kind != "boundary":
                        continue
                    actual = value
                    if field["type"] == "select":
                        options = [o for o in field["options"] if o not in ("",)]
                        if not options:
                            continue
                        actual = options[-1]
                    state = await page.evaluate(
                        _FILL_AND_READ_JS, {"probe": field["probe"], "value": actual}
                    )
                    probed += 1
                    if not state:
                        continue
                    label = field["label"] or field["name"] or field["id"] or field["type"]
                    # Silent failure: clearly invalid input accepted with no feedback at all.
                    if kind == "invalid" and state["valid"] and not state["message"]:
                        findings.append(
                            Finding(
                                id=finding_id("forms", f"silent-accept-{field['type']}", form_label, field["probe"]),
                                category="forms",
                                severity="high",
                                title=f"Invalid {field['type']} accepted silently: “{label}”",
                                detail=(
                                    f"Filled “{value}” into field “{label}” on form “{form_label}”. "
                                    f"The field reports valid with no validation message, so a user can "
                                    f"submit garbage and only discover it server-side. ({intent})"
                                ),
                                evidence={
                                    "form": form_label, "field": label, "type": field["type"],
                                    "value": str(value)[:60], "required": field["required"],
                                    "validationMessage": state["message"], "probe_kind": kind,
                                },
                                recommendation=(
                                    "Add client-side validation (input type, pattern, or explicit "
                                    "validation rules) and surface the error text next to the field."
                                ),
                            )
                        )
                    # Required-but-unenforced, or validation with no accessible announcement.
                    elif state["invalidPseudo"] and not state["message"] and not state["ariaInvalid"]:
                        findings.append(
                            Finding(
                                id=finding_id("forms", "unannounced-invalid", form_label, field["probe"]),
                                category="forms",
                                severity="medium",
                                title=f"Validation error not announced to assistive tech: “{label}”",
                                detail=(
                                    f"Field “{label}” is marked :invalid but exposes no validationMessage, "
                                    f"no aria-invalid and no aria-describedby target, so screen-reader "
                                    f"users get no explanation of the failure."
                                ),
                                evidence={"form": form_label, "field": label, "type": field["type"],
                                          "value": str(value)[:60]},
                                recommendation=(
                                    "Set aria-invalid=\"true\" and point aria-describedby at the visible "
                                    "error message; keep the message in the DOM, not a transient tooltip."
                                ),
                            )
                        )
                # Unbounded text input.
                if field["tag"] == "input" and field["type"] in ("text", "search") and not field["maxlength"]:
                    findings.append(
                        Finding(
                            id=finding_id("forms", "no-maxlength", form_label, field["probe"]),
                            category="forms",
                            severity="low",
                            title=f"No maxlength on text field: “{field['label'] or field['name']}”",
                            detail=(
                                "A 512-character value was accepted. Without a maxlength the field "
                                "invites oversized input, which is a data-quality and DoS-surface risk."
                            ),
                            evidence={"form": form_label, "field": field["label"] or field["name"],
                                      "accepted_length": 512},
                            recommendation="Set a realistic maxlength and validate server-side too.",
                        )
                    )
        attempts = await page.evaluate("() => window.__submitAttempts || []")
        log(f"probed {probed} field/value combinations; submission attempts recorded: {len(attempts)}")
        if attempts:
            findings.append(
                Finding(
                    id=finding_id("forms", "submit-attempt-blocked"),
                    category="forms",
                    severity="info",
                    title="Guardrail intercepted a submission attempt",
                    detail=(
                        f"{len(attempts)} submit attempt(s) were blocked by the guardrail "
                        f"({', '.join(sorted(set(a.split(':')[0] for a in attempts)))}). "
                        "Nothing was sent — the network layer aborts all non-GET requests."
                    ),
                    evidence={"attempts": attempts[:5]},
                    recommendation="No action required; recorded for transparency.",
                )
            )
    finally:
        await context.close()
    return findings
