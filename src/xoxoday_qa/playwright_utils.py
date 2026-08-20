"""Shared Playwright helpers used by every specialist agent.

Centralizing this means the rate-limit and console/network-monitor logic
(the two things every agent must not get wrong) is written once.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from .config import RUN, SAFETY

_last_request_time: dict[str, float] = {}


def throttle(shard_key: str = "default") -> None:
    """Enforce SAFETY.min_delay_seconds between requests.

    Call this immediately before every page.goto(). The scan behaves like
    one polite visitor, not a load test — this is the enforcement point.
    """
    now = time.monotonic()
    last = _last_request_time.get(shard_key, 0.0)
    wait = SAFETY.min_delay_seconds - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_time[shard_key] = time.monotonic()


@dataclass
class PageMonitor:
    """Captures console errors and non-2xx/failed network responses for a page load.

    This is the mechanism behind the "silent failures" capability (200 OK
    with an error payload, dead third-party embeds, JS console errors that
    don't visually break anything).
    """

    console_errors: list[str] = field(default_factory=list)
    network_failures: list[dict[str, Any]] = field(default_factory=list)

    def attach(self, page: Page) -> None:
        page.on("console", self._on_console)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_request_failed)

    def _on_console(self, msg) -> None:
        if msg.type == "error":
            self.console_errors.append(msg.text)

    def _on_response(self, response) -> None:
        try:
            if response.status >= 400:
                self.network_failures.append({
                    "url": response.url,
                    "status": response.status,
                    "kind": "http_error",
                })
            elif response.status == 200 and _looks_like_api_call(response.url):
                # Cheap heuristic for "200 with an error payload in the body":
                # flag JSON API responses whose body contains common error
                # markers. Full body inspection happens in forms_agent for
                # endpoints it deliberately exercises; this is the passive,
                # every-page-load version.
                ctype = response.headers.get("content-type", "")
                if "json" in ctype:
                    try:
                        body = response.text()
                        if _looks_like_error_payload(body):
                            self.network_failures.append({
                                "url": response.url,
                                "status": 200,
                                "kind": "silent_error_payload",
                            })
                    except Exception:
                        pass
        except Exception:
            pass

    def _on_request_failed(self, request) -> None:
        self.network_failures.append({
            "url": request.url,
            "status": None,
            "kind": "request_failed",
            "failure": request.failure,
        })


def _looks_like_api_call(url: str) -> bool:
    return any(marker in url for marker in ("/api/", "/graphql", "/v1/", "/v2/"))


def _looks_like_error_payload(body: str) -> bool:
    lowered = body.lower()
    return any(m in lowered for m in ('"error"', '"success":false', '"ok":false', '"status":"error"'))


@contextmanager
def browser_session() -> Iterator[Browser]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


def new_context(browser: Browser, viewport: dict[str, int]) -> BrowserContext:
    return browser.new_context(
        viewport=viewport,
        user_agent=SAFETY.resolved_user_agent(),
    )


def goto_and_settle(page: Page, url: str, timeout_ms: int = 30_000, settle_ms: int = 1_500):
    """Navigate without making long-lived background requests a hard failure.

    Marketing sites commonly keep analytics, chat, or streaming connections
    open, so Playwright's ``networkidle`` condition may never be reached even
    when the document is fully usable. Wait for DOM content, then give the
    page a brief best-effort settling window for client-side hydration.
    """
    response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(settle_ms)
    return response


def screenshot_at_breakpoints(browser: Browser, url: str, out_dir: str, shard_key: str = "default") -> dict[str, str]:
    """Load `url` at each configured viewport and save a full-page screenshot.

    Returns {breakpoint_name: file_path}.
    """
    import os
    os.makedirs(out_dir, exist_ok=True)
    paths: dict[str, str] = {}

    for name, viewport in RUN.viewports.items():
        ctx = new_context(browser, viewport)
        page = ctx.new_page()
        throttle(shard_key)
        goto_and_settle(page, url)
        safe_name = url.rstrip("/").split("/")[-1] or "home"
        path = os.path.join(out_dir, f"{safe_name}_{name}.png")
        page.screenshot(path=path, full_page=True)
        paths[name] = path
        ctx.close()

    return paths
