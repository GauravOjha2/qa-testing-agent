"""robots.txt handling — fail closed.

Policy (documented in every report):
  * robots.txt fetched with the honest SiteSentinel UA before any page load.
  * 2xx  -> parsed with urllib.robotparser; Disallow wins.
  * 404  -> no robots file exists; RFC 9309 treats that as allow-all.
  * other 4xx -> allow (RFC 9309 "unavailable" semantics).
  * network error / timeout / 5xx -> FAIL CLOSED: the scan is refused,
    because we could not verify the site owner permits automated access.
"""

from __future__ import annotations

import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from . import config
from .ratelimit import RateLimiter


class RobotsDenied(PermissionError):
    """Scan refused: robots.txt disallows us or could not be verified."""


@dataclass
class RobotsVerdict:
    allowed: bool
    reason: str
    robots_url: str


async def check_allowed(url: str, limiter: RateLimiter) -> RobotsVerdict:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    await limiter.wait()
    try:
        async with httpx.AsyncClient(
            timeout=config.ROBOTS_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
            follow_redirects=True,
        ) as client:
            resp = await client.get(robots_url)
    except Exception as exc:  # noqa: BLE001 - any fetch failure fails closed
        raise RobotsDenied(
            f"Could not retrieve {robots_url} ({exc}). Fail-closed policy: "
            "the scan is refused because site-owner consent cannot be verified."
        ) from exc

    if resp.status_code >= 500:
        raise RobotsDenied(
            f"{robots_url} returned HTTP {resp.status_code}. Fail-closed policy: "
            "the scan is refused until robots.txt is reachable."
        )
    if resp.status_code == 404:
        return RobotsVerdict(True, "no robots.txt (HTTP 404) — allowed by RFC 9309", robots_url)
    if resp.status_code >= 400:
        return RobotsVerdict(True, f"robots.txt HTTP {resp.status_code} — allowed by RFC 9309", robots_url)

    parser = urllib.robotparser.RobotFileParser()
    parser.parse(resp.text.splitlines())
    if not parser.can_fetch(config.USER_AGENT, url):
        raise RobotsDenied(
            f"robots.txt at {robots_url} disallows this scanner from fetching {url}."
        )
    return RobotsVerdict(True, "robots.txt permits this scanner", robots_url)
