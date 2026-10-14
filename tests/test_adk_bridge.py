"""Unit tests for the ADK bridge (app/adk_engine.py) and the ADK agent layer.

Offline: no browser, no network, no Gemini calls. These tests pin the
deterministic half of the ADK engine — the part that turns tool payloads
and agent text into findings, vitals and stage metadata.
"""

from __future__ import annotations

import re
from pathlib import Path

from app import config
from app.adk_engine import (
    _axe_findings,
    _extract_json,
    _forms_findings,
    _geo_findings,
    _perf_findings,
    _resp_count,
    _sev,
    _visual_findings,
    _vitals_from,
)
from adk_qa_pipeline.agents import (
    FLASH_MODEL,
    PRO_MODEL,
    prevent_form_submit_guardrail,
)

REPO = Path(__file__).resolve().parents[1]


# --- model policy ------------------------------------------------------------

def test_all_agents_on_flash():
    assert FLASH_MODEL == "gemini-flash-latest"
    assert PRO_MODEL == "gemini-flash-latest"  # policy: flash-only, no Pro


def test_no_pro_model_anywhere():
    offenders = []
    for path in list(REPO.glob("app/**/*.py")) + list(REPO.glob("adk_qa_pipeline/**/*.py")) + [REPO / "server.py"]:
        if "gemini-pro" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert not offenders, f"gemini-pro references remain in {offenders}"


def test_engine_config_defaults():
    assert config.ENGINE in ("adk", "core")
    assert config.ADK_STALL_TIMEOUT > 0
    assert config.ADK_TOTAL_BUDGET > config.ADK_STALL_TIMEOUT


# --- no-submit guardrail ------------------------------------------------------

class _FakeTool:
    def __init__(self, name):
        self.name = name


def test_guardrail_blocks_submit_intent_tool_name():
    out = prevent_form_submit_guardrail(_FakeTool("submit_form"), {"url": "https://x.com"})
    assert out and out["status"] == "blocked"


def test_guardrail_blocks_submit_click_args():
    out = prevent_form_submit_guardrail(
        _FakeTool("click_element"), {"selector": 'button[type="submit"]'})
    assert out and out["status"] == "blocked"


def test_guardrail_blocks_action_submit():
    out = prevent_form_submit_guardrail(_FakeTool("form_action"), {"action": "submit"})
    assert out and out["status"] == "blocked"


def test_guardrail_blocks_form_tool_pointed_at_submit_control():
    out = prevent_form_submit_guardrail(
        _FakeTool("test_form_boundaries"), {"url": "https://x.com", "selector": '[type="submit"]'})
    assert out and out["status"] == "blocked"


def test_guardrail_allows_normal_boundary_test():
    out = prevent_form_submit_guardrail(
        _FakeTool("test_form_boundaries"), {"url": "https://x.com", "selector": "form"})
    assert out is None


# --- payload -> finding translation -------------------------------------------

AXE_PAYLOAD = {
    "status": "ok",
    "findings": [
        {"severity": "serious", "title": "A11y: label — form elements must have labels",
         "detail": "WCAG.", "tags": ["a11y", "wcag", "label"],
         "affected_selectors": ["#email", "#name"]},
        {"severity": "moderate", "title": "JS console error (no visible break)",
         "detail": "boom", "tags": ["silent-failure", "console-error"]},
        {"severity": "bogus", "title": "Weird severity", "detail": "", "tags": ["a11y"]},
    ],
}


def test_axe_translation_categories_and_severity():
    findings = _axe_findings(AXE_PAYLOAD)
    assert len(findings) == 3
    assert findings[0].category == "accessibility"
    assert findings[0].severity == "serious" or findings[0].severity in ("critical", "high", "medium", "low", "info")
    assert findings[1].category == "technical"
    assert findings[2].severity == "medium"  # bogus severity normalised
    assert findings[0].evidence["selector"] == "#email"


def test_finding_ids_deterministic():
    a = _axe_findings(AXE_PAYLOAD)
    b = _axe_findings(AXE_PAYLOAD)
    assert [f.id for f in a] == [f.id for f in b]


GEO_TEXT = """
Ground truth captured.
1. What does the product do? — SUPPORTED. The page states it plainly.
2. Does it ship worldwide? — UNSUPPORTED. The page never claims global delivery.
3. Is there a free tier? — NOT_MENTIONED anywhere on the page.
GEO_AEO_DONE: 1 unsupported, 1 not-mentioned
"""


def test_geo_findings_parse():
    findings = _geo_findings(GEO_TEXT)
    sevs = [f.severity for f in findings]
    assert sevs.count("high") == 1   # UNSUPPORTED
    assert sevs.count("medium") == 1 # NOT_MENTIONED
    assert all(f.category == "geo_aeo" for f in findings)


def test_geo_findings_empty_when_no_markers():
    assert _geo_findings("everything looks fine, all supported") == []


def test_extract_json_fenced_and_plain():
    assert _extract_json('prefix {"a": 1, "b": [2]} suffix') == {"a": 1, "b": [2]}
    assert _extract_json("no json here") is None


def test_vitals_mapping():
    vitals = _vitals_from({
        "status": "ok",
        "metrics": {"LCP": 1800.0, "CLS": 0.02},
        "scores": {"performance": 0.91, "accessibility": 0.8},
    })
    assert vitals["lcp_ms"] == 1800.0
    assert vitals["cls"] == 0.02
    assert vitals["performance_score"] == 91
    assert vitals["source"] == "lighthouse-cli"
    assert "INP" in vitals["inp_note"]


def test_visual_forms_perf_translators():
    v = _visual_findings({"findings": [{"severity": "high", "title": "[mobile] horizontal overflow detected",
                                        "detail": "scrollWidth=500", "evidence_uri": "x.png"}]})
    assert v[0].category == "visual" and v[0].severity == "high"
    f = _forms_findings({"findings": [{"severity": "medium", "title": "Invalid email accepted", "detail": "d"}]})
    assert f[0].category == "forms"
    p = _perf_findings({"findings": [{"title": "LCP exceeds 'good' threshold", "detail": "LCP = 5000"}]})
    assert p[0].category == "performance" and p[0].severity == "medium"


def test_resp_count_from_compact_payloads():
    assert _resp_count("run_axe_core_audit", {"violation_count": 7}) == 7
    assert _resp_count("capture_viewport_screenshots", {"finding_count": 2}) == 2
    assert _resp_count("test_form_boundaries", {"findings": [{}, {}, {}]}) == 3
    assert _resp_count("fetch_page_text_snapshot", {}) == 0


def test_sev_normalisation():
    assert _sev("critical") == "critical"
    assert _sev("nonsense") == "medium"
    assert _sev(None, "info") == "info"

def test_adk_engine_imports_cleanly():
    """The server falls back to core if this import breaks — pin it so a
    broken ADK bridge can never silently degrade the product."""
    import importlib
    mod = importlib.import_module("app.adk_engine")
    assert callable(mod.run_scan)


def test_server_engine_selection():
    import server
    assert server._ENGINE == "adk"
