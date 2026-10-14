"""Shared Playwright helpers: one browser per scan, polite contexts."""

from __future__ import annotations

from typing import Any

from playwright.async_api import Browser, BrowserContext

from .. import config
from ..ratelimit import RateLimiter


async def new_context(
    browser: Browser,
    viewport: dict[str, int],
    *,
    extra_init_script: str | None = None,
    block_mutations: bool = False,
) -> BrowserContext:
    """Create a context stamped with the honest UA and optional guardrails."""
    context = await browser.new_context(
        viewport=viewport,
        user_agent=config.USER_AGENT,
        device_scale_factor=2 if viewport["width"] < 500 else 1,
        ignore_https_errors=False,
        java_script_enabled=True,
    )
    context.set_default_navigation_timeout(config.NAV_TIMEOUT_MS)
    context.set_default_timeout(config.NAV_TIMEOUT_MS)
    if extra_init_script:
        await context.add_init_script(extra_init_script)
    if block_mutations:
        # Hard network guardrail: no non-GET request may leave the browser.
        async def _guard(route):  # type: ignore[no-untyped-def]
            if route.request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                await route.abort()
            else:
                await route.continue_()
        await context.route("**/*", _guard)
    return context


async def goto_polite(page: Any, url: str, limiter: RateLimiter) -> Any:
    """Navigate with the shared politeness throttle applied first."""
    await limiter.wait()
    return await page.goto(url, wait_until="domcontentloaded")
