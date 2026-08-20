import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx

from xoxoday_qa import crawler  # noqa: E402
from xoxoday_qa.crawler import classify, select_demo_subset  # noqa: E402
from xoxoday_qa.dom_utils import read_meta_description  # noqa: E402
from xoxoday_qa.playwright_utils import goto_and_settle  # noqa: E402
from xoxoday_qa.agents.forms_agent import _check_validation_state, _find_field  # noqa: E402
from xoxoday_qa.models import PageType  # noqa: E402


def test_classify_homepage():
    t = classify("https://www.xoxoday.com/")
    assert t.page_type == PageType.HOMEPAGE
    assert t.priority == 1


def test_classify_localized_product_page():
    t = classify("https://www.xoxoday.com/de/empuls/")
    assert t.locale == "de"
    assert t.page_type == PageType.LOCALIZED


def test_classify_demo_form():
    t = classify("https://www.xoxoday.com/request-demo/")
    assert t.page_type == PageType.DEMO_FORM


def test_demo_subset_covers_key_types():
    urls = [
        "https://www.xoxoday.com/",
        "https://www.xoxoday.com/pricing/",
        "https://www.xoxoday.com/empuls/",
        "https://www.xoxoday.com/industries/retail/",
        "https://www.xoxoday.com/blog/some-post/",
        "https://www.xoxoday.com/de/plum/",
        "https://www.xoxoday.com/request-demo/",
        "https://www.xoxoday.com/about/",
    ]
    targets = [classify(u) for u in urls]
    subset = select_demo_subset(targets, n=6)
    types_covered = {t.page_type for t in subset}
    assert PageType.HOMEPAGE in types_covered
    assert PageType.PRICING_ROI in types_covered
    assert len(subset) <= 6


def test_sitemap_fetch_retries_a_rate_limit(monkeypatch):
    request = httpx.Request("GET", "https://example.com/sitemap.xml")
    responses = [
        httpx.Response(429, headers={"Retry-After": "0"}, request=request),
        httpx.Response(200, content=b"<urlset/>", request=request),
    ]
    monkeypatch.setattr(crawler.httpx, "get", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr(crawler.time, "sleep", lambda *_: None)

    assert crawler._fetch_sitemap("https://example.com/sitemap.xml").status_code == 200


def test_metadata_read_uses_immediate_dom_evaluation():
    class FakePage:
        def __init__(self):
            self.script = None

        def evaluate(self, script):
            self.script = script
            return "A page description"

        def locator(self, *_args, **_kwargs):
            raise AssertionError("Metadata extraction must not wait on a locator")

    page = FakePage()
    assert read_meta_description(page) == "A page description"
    assert "querySelector" in page.script


def test_navigation_does_not_fail_when_network_never_becomes_idle():
    class FakePage:
        def __init__(self):
            self.goto_args = None
            self.settled = False

        def goto(self, *args, **kwargs):
            self.goto_args = (args, kwargs)
            return "response"

        def wait_for_load_state(self, *_args, **_kwargs):
            from playwright.sync_api import TimeoutError
            raise TimeoutError("background connection remains open")

        def wait_for_timeout(self, _ms):
            self.settled = True

    page = FakePage()
    assert goto_and_settle(page, "https://example.com", settle_ms=0) == "response"
    assert page.goto_args[1]["wait_until"] == "domcontentloaded"
    assert page.settled


def test_invalid_email_returns_a_normal_finding():
    class FakeField:
        def get_attribute(self, name):
            assert name == "aria-invalid"
            return None

    finding = _check_validation_state(
        FakeField(),
        {"field_hint": "email", "value": "not-an-email"},
    )
    assert finding is not None
    assert "Invalid email" in finding.title


def test_form_field_lookup_ignores_hidden_input():
    class Candidate:
        def __init__(self, visible):
            self.visible = visible

        def is_visible(self):
            return self.visible

    class Locator:
        def __init__(self):
            self.items = [Candidate(False), Candidate(True)]

        def count(self):
            return len(self.items)

        def nth(self, index):
            return self.items[index]

    class Form:
        def locator(self, _selector):
            return Locator()

    assert _find_field(Form(), "email").visible is True


if __name__ == "__main__":
    test_classify_homepage()
    test_classify_localized_product_page()
    test_classify_demo_form()
    test_demo_subset_covers_key_types()
    print("All tests passed.")
