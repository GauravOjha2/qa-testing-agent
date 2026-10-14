"""Shared per-origin politeness throttle.

Every request we initiate to the target origin (robots fetch, page
navigations, sub-resource-heavy stages) flows through `wait()`, which
enforces a minimum gap of THROTTLE_SECONDS between hits."""

from __future__ import annotations

import asyncio
import time

from . import config


class RateLimiter:
    def __init__(self, min_interval: float = config.THROTTLE_SECONDS) -> None:
        self._min_interval = min_interval
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            gap = time.monotonic() - self._last
            if gap < self._min_interval:
                await asyncio.sleep(self._min_interval - gap)
            self._last = time.monotonic()
