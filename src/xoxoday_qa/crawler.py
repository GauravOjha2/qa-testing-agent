"""Sitemap discovery + page classification.

Discovers candidate URLs from the target's sitemap, classifies each by
page type, and checks robots.txt. It never touches page content itself —
actual page interaction happens in the specialist agents.
"""

from __future__ import annotations

import re
import time
import urllib.robotparser as robotparser
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import httpx

from .config import RUN, SAFETY
from .models import PageTarget, PageType

_LOCALE_PATH_RE = re.compile(r"^/([a-z]{2}(-[a-z]{2})?)/", re.IGNORECASE)

_TYPE_HINTS: list[tuple[re.Pattern, PageType]] = [
    (re.compile(r"^/$"), PageType.HOMEPAGE),
    # [/-] boundary so hyphenated slugs like /plum-pricing/ classify as
    # pricing rather than falling through to OTHER.
    (re.compile(r"[/-](pricing|roi-calculator|calculator)"), PageType.PRICING_ROI),
    (re.compile(r"/(empuls|plum|compass)([/\-_]|$)"), PageType.PRODUCT),
    (re.compile(r"/(industries|solutions)/"), PageType.INDUSTRY_LANDING),
    (re.compile(r"/blog/"), PageType.BLOG),
    (re.compile(r"/(request-demo|talk-to-sales|book-a-demo|contact)"), PageType.DEMO_FORM),
]

_SITEMAP_MAX_ATTEMPTS = 3


def _fetch_sitemap(url: str) -> httpx.Response:
    """Fetch one sitemap with bounded, server-directed retry behavior.

    A 429 is not an invitation to keep crawling aggressively.  Respect the
    server's Retry-After value when supplied, otherwise make only a couple of
    increasingly delayed attempts and surface the error to the caller.
    """
    for attempt in range(_SITEMAP_MAX_ATTEMPTS):
        response = httpx.get(
            url,
            headers={"User-Agent": SAFETY.resolved_user_agent()},
            timeout=15.0,
        )
        if response.status_code != 429:
            response.raise_for_status()
            return response

        if attempt == _SITEMAP_MAX_ATTEMPTS - 1:
            response.raise_for_status()

        try:
            retry_after = float(response.headers.get("Retry-After", ""))
        except ValueError:
            retry_after = 0.0
        time.sleep(min(max(retry_after, 2.0 * (attempt + 1)), 30.0))

    raise RuntimeError("unreachable")  # pragma: no cover - satisfies type checkers


def classify(url: str) -> PageTarget:
    path = urlparse(url).path or "/"
    locale = "en"
    m = _LOCALE_PATH_RE.match(path)
    if m:
        locale = m.group(1).lower()

    page_type = PageType.OTHER
    for pattern, ptype in _TYPE_HINTS:
        if pattern.search(path):
            page_type = ptype
            break

    if locale != "en" and page_type != PageType.OTHER:
        page_type = PageType.LOCALIZED

    priority = {
        PageType.HOMEPAGE: 1,
        PageType.PRICING_ROI: 1,
        PageType.PRODUCT: 2,
        PageType.LOCALIZED: 2,
        PageType.DEMO_FORM: 2,
        PageType.INDUSTRY_LANDING: 3,
        PageType.BLOG: 4,
        PageType.OTHER: 5,
    }[page_type]

    return PageTarget(url=url, page_type=page_type, locale=locale, priority=priority)


def check_robots_allowed(base_url: str, user_agent: str) -> robotparser.RobotFileParser:
    """Fetch and parse robots.txt once; caller uses .can_fetch() per URL."""
    rp = robotparser.RobotFileParser()
    robots_url = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}/robots.txt"
    try:
        resp = httpx.get(robots_url, headers={"User-Agent": user_agent}, timeout=10.0)
        rp.parse(resp.text.splitlines())
    except httpx.HTTPError:
        # If robots.txt is unreachable, fail closed: parse() with no rules
        # means can_fetch() defaults to allow, which is the wrong default
        # for a safety-first crawler. Explicitly disallow everything until
        # we can confirm the rules.
        rp.disallow_all = True
    return rp


def discover_urls(sitemap_url: str | None = None) -> list[str]:
    """Recursively expand sitemap / sitemap-index XML into a flat URL list."""
    sitemap_url = sitemap_url or RUN.sitemap_url
    urls: list[str] = []
    to_fetch = [sitemap_url]
    seen_sitemaps: set[str] = set()

    while to_fetch:
        current = to_fetch.pop()
        if current in seen_sitemaps:
            continue
        seen_sitemaps.add(current)

        resp = _fetch_sitemap(current)
        root = ET.fromstring(resp.content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        # sitemap index -> more sitemaps
        for sm in root.findall("sm:sitemap/sm:loc", ns):
            if sm.text:
                to_fetch.append(sm.text.strip())

        # actual page entries
        for loc in root.findall("sm:url/sm:loc", ns):
            if loc.text:
                urls.append(loc.text.strip())

    return urls


def build_target_list(sitemap_url: str | None = None) -> list[PageTarget]:
    """Full discover -> classify -> robots-filter pipeline."""
    raw_urls = discover_urls(sitemap_url)
    rp = check_robots_allowed(RUN.target_domain, SAFETY.resolved_user_agent())

    targets = []
    for url in raw_urls:
        if SAFETY.respect_robots_txt and not rp.can_fetch(SAFETY.resolved_user_agent(), url):
            continue
        targets.append(classify(url))

    return targets


def select_demo_subset(targets: list[PageTarget], n: int | None = None) -> list[PageTarget]:
    """Pick a representative, not random, subset for the timeboxed demo run.

    Guarantees at least one of each high-value page type (per the brief:
    homepage, pricing/ROI, one product page, one industry landing page,
    one blog post, one localized page) before filling remaining slots by
    priority.
    """
    n = n or RUN.demo_subset_size
    by_type: dict[PageType, list[PageTarget]] = {}
    for t in targets:
        by_type.setdefault(t.page_type, []).append(t)

    must_have_order = [
        PageType.HOMEPAGE,
        PageType.PRICING_ROI,
        PageType.PRODUCT,
        PageType.INDUSTRY_LANDING,
        PageType.BLOG,
        PageType.LOCALIZED,
        PageType.DEMO_FORM,
    ]

    subset: list[PageTarget] = []
    chosen_urls: set[str] = set()

    for ptype in must_have_order:
        candidates = by_type.get(ptype, [])
        if candidates:
            pick = candidates[0]
            subset.append(pick)
            chosen_urls.add(pick.url)

    remaining = sorted(
        (t for t in targets if t.url not in chosen_urls),
        key=lambda t: t.priority,
    )
    for t in remaining:
        if len(subset) >= n:
            break
        subset.append(t)
        chosen_urls.add(t.url)

    return subset[:n]
