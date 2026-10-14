"""Offline unit tests for the SiteSentinel engine core.

These run without network access: robots.txt behaviour is exercised with a
stubbed transport, and the guardrail test asserts statically that no submit
code path exists in the forms stage.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app import config, report
from app.models import Finding, ScanResult, dedup_findings, finding_id, severity_counts
from app.ratelimit import RateLimiter
from app.robots import RobotsDenied, check_allowed
from app.stages import forms as forms_stage


class _Resp:
    def __init__(self, status: int, text: str = "") -> None:
        self.status_code = status
        self.text = text


class _FakeClient:
    """Stands in for httpx.AsyncClient with a scripted robots.txt reply."""

    def __init__(self, resp=None, error=None) -> None:
        self._resp, self._error = resp, error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):  # noqa: D401
        if self._error:
            raise self._error
        return self._resp


def _patch_client(monkeypatch, resp=None, error=None):
    import httpx

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp=resp, error=error)
    )


# --- robots.txt: fail-closed ------------------------------------------------

@pytest.mark.asyncio
async def test_robots_network_error_fails_closed(monkeypatch):
    _patch_client(monkeypatch, error=OSError("dns boom"))
    with pytest.raises(RobotsDenied):
        await check_allowed("https://example.com/", RateLimiter(0))


@pytest.mark.asyncio
async def test_robots_5xx_fails_closed(monkeypatch):
    _patch_client(monkeypatch, resp=_Resp(503))
    with pytest.raises(RobotsDenied):
        await check_allowed("https://example.com/", RateLimiter(0))


@pytest.mark.asyncio
async def test_robots_404_allows(monkeypatch):
    _patch_client(monkeypatch, resp=_Resp(404))
    verdict = await check_allowed("https://example.com/", RateLimiter(0))
    assert verdict.allowed


@pytest.mark.asyncio
async def test_robots_disallow_blocks(monkeypatch):
    body = "User-agent: *\nDisallow: /\n"
    _patch_client(monkeypatch, resp=_Resp(200, body))
    with pytest.raises(RobotsDenied):
        await check_allowed("https://example.com/", RateLimiter(0))


@pytest.mark.asyncio
async def test_robots_allow_permits(monkeypatch):
    _patch_client(monkeypatch, resp=_Resp(200, "User-agent: *\nDisallow: /admin\n"))
    verdict = await check_allowed("https://example.com/pricing", RateLimiter(0))
    assert verdict.allowed and "permits" in verdict.reason


# --- findings: dedup + determinism -----------------------------------------

def test_finding_ids_are_deterministic():
    assert finding_id("forms", "no-maxlength", "f0", "2") == finding_id("forms", "no-maxlength", "f0", "2")
    assert finding_id("forms", "no-maxlength", "f0", "2") != finding_id("forms", "no-maxlength", "f0", "3")


def test_dedup_collapses_and_sorts_by_severity():
    dupes = [
        Finding(id="a", category="accessibility", severity="medium", title="Contrast",
                evidence={"selector": "#cta"}),
        Finding(id="b", category="accessibility", severity="medium", title="Contrast",
                evidence={"selector": "#cta"}),
        Finding(id="c", category="visual", severity="critical", title="Overflow",
                evidence={"selector": "body"}),
    ]
    unique = dedup_findings(dupes)
    assert len(unique) == 2
    assert unique[0].severity == "critical"
    assert severity_counts(unique) == {"critical": 1, "high": 0, "medium": 1, "low": 0, "info": 0}


# --- guardrail: there is no submit code path --------------------------------

def test_forms_stage_has_no_submit_call_path():
    """Static guardrail proof: walk the AST of the forms stage and assert
    that no call anywhere invokes submit/requestSubmit, presses Enter, or
    clicks a submit button. Docstrings and comments (which merely *name*
    the guardrail) are ignored, because the AST only contains real code."""
    tree = ast.parse(inspect.getsource(forms_stage))
    forbidden_attrs = {"submit", "requestSubmit"}
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in forbidden_attrs:
                offenders.append(func.attr)
            if isinstance(func, ast.Name) and func.id in forbidden_attrs:
                offenders.append(func.id)
            if isinstance(func, ast.Attribute) and func.attr in {"press", "click"}:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        text = arg.value
                        if text in {"Enter", "NumpadEnter"} or "submit" in text.lower():
                            offenders.append(f"{func.attr}({text!r})")

    assert not offenders, f"forms stage must not contain submit paths: {offenders}"

    # The safety layers must still be wired up.
    source = inspect.getsource(forms_stage)
    assert "block_mutations=True" in source, "forms context must abort non-GET requests"
    assert "HTMLFormElement.prototype.submit" in source, "guardrail init script must stub submit"


# --- report ---------------------------------------------------------------

def _sample_result() -> ScanResult:
    return ScanResult(
        scan_id="abc123",
        target_url="https://example.com/",
        final_url="https://example.com/",
        scanned_at="2026-01-01T00:00:00+00:00",
        elapsed_seconds=42.0,
        user_agent=config.USER_AGENT,
        model=config.GEMINI_MODEL,
        severity_counts={"critical": 1, "high": 0, "medium": 0, "low": 0, "info": 0},
        findings=[Finding(id="x1", category="visual", severity="critical", title="Horizontal overflow",
                          detail="scrolls 120px", recommendation="fix widths")],
        top_risks=["Mobile layout breaks horizontally"],
        executive_summary="One critical issue.",
        safety={"robots_url": "https://example.com/robots.txt", "robots_txt": "permits",
                "user_agent": config.USER_AGENT, "forms_submitted": 0, "ai_model": config.GEMINI_MODEL,
                "ai_model_policy": "Every AI layer runs on gemini-flash-latest only."},
    )


def test_report_html_contains_cover_kpis_and_safety():
    html_doc = report.build_html(_sample_result())
    assert "Website" in html_doc and "Quality &amp; Risk" in html_doc
    assert "Executive summary" in html_doc
    assert "Safety &amp; compliance statement" in html_doc
    assert "gemini-flash-latest" in html_doc
    assert "Horizontal overflow" in html_doc
    assert "@page" in html_doc  # A4 page setup present


def test_model_is_gemini_flash_latest():
    assert config.GEMINI_MODEL == "gemini-flash-latest"


def test_static_assets_exist():
    for name in ("index.html", "app.css", "app.js"):
        assert (Path(config.STATIC_DIR) / name).is_file()


# --- URL validation --------------------------------------------------------

def test_validate_url_adds_https_prefix(monkeypatch):
    import socket
    from server import _validate_url
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [(socket.AF_INET, 0, 0, '', ('93.184.215.14', 0))])
    assert _validate_url("example.com").startswith("https://")


def test_validate_url_rejects_empty():
    from server import _validate_url
    with pytest.raises(Exception):
        _validate_url("")


def test_validate_url_rejects_private_hosts():
    from server import _validate_url
    with pytest.raises(Exception):
        _validate_url("http://localhost/")


def test_validate_url_blocks_metadata():
    from server import _validate_url
    with pytest.raises(Exception):
        _validate_url("http://metadata.google.internal/")


def test_validate_url_rejects_private_ip(monkeypatch):
    import socket
    from server import _validate_url
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [(socket.AF_INET, 0, 0, '', ('192.168.1.1', 0))])
    with pytest.raises(Exception):
        _validate_url("http://corp-internal.test")


# --- LLM JSON extraction ---------------------------------------------------

def test_extract_json_plain():
    from app.llm import _extract_json
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    from app.llm import _extract_json
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_preamble():
    from app.llm import _extract_json
    assert _extract_json('Here is the result:\n{"a": 1}') == {"a": 1}


# --- report determinism -----------------------------------------------------

def test_report_html_is_deterministic():
    r = _sample_result()
    html1 = report.build_html(r)
    html2 = report.build_html(r)
    assert html1 == html2


# --- config -----------------------------------------------------------------

def test_severity_order_matches_model_literal():
    """Verify config.SEVERITY_ORDER matches the Severity literal."""
    import typing
    from app.models import Severity
    args = typing.get_args(Severity)
    assert list(args) == config.SEVERITY_ORDER

