"""Central configuration.

Everything that governs how aggressively this agent hits a *live business's*
production site lives here, in one place, so it's auditable at a glance.
See the production-safety checklist in README.md — this file is the
enforcement point for most of it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class SafetyConfig:
    # Identify ourselves honestly. A real, contactable UA is non-negotiable
    # for anything crawling a third party's live production site.
    user_agent: str = (
        "XoxodayQAAgent/1.0 (+mailto:{contact}; automated QA scan, "
        "run at requester's invitation, respects robots.txt)"
    )
    contact_email: str = os.environ.get("QA_AGENT_CONTACT_EMAIL", "REPLACE_WITH_YOUR_EMAIL")

    respect_robots_txt: bool = True

    # Rate limiting: minimum delay between consecutive page loads, so the
    # scan behaves like a polite single visitor rather than a load test.
    min_delay_seconds: float = 1.5

    # Forms: absolute hard stop. The agent is never allowed to complete
    # a real submission on these form types, regardless of what any other
    # setting says. Enforced in agents/forms_agent.py — see NEVER_SUBMIT.
    never_submit_real_forms: bool = True
    dummy_data_marker: str = "QA-Agent-Test — please disregard"

    def resolved_user_agent(self) -> str:
        return self.user_agent.format(contact=self.contact_email)


@dataclass
class RunConfig:
    target_domain: str = os.environ.get("QA_TARGET_DOMAIN", "https://www.xoxoday.com")
    sitemap_url: str = os.environ.get("QA_SITEMAP_URL", "https://www.xoxoday.com/sitemap.xml")

    # Full-site architecture target vs. what we actually demo against.
    full_site_page_count_estimate: int = 200
    demo_subset_size: int = 20  # 15-25 per brief; representative, not random

    # Viewports for visual QA (mobile / tablet / desktop)
    viewports: dict = field(default_factory=lambda: {
        "mobile": {"width": 390, "height": 844},
        "tablet": {"width": 834, "height": 1194},
        "desktop": {"width": 1440, "height": 900},
    })

    # GEO/AEO: which answer engines to cross-check against. Each needs its
    # own API key in env; agent skips any engine whose key is unset rather
    # than failing the whole run.
    llm_engines_for_geo_check: list = field(default_factory=lambda: [
        "gemini", "claude", "perplexity",
    ])

    # Where run artifacts live. Findings are written to ./local_findings/
    # as JSON; screenshots go to ./screenshots/local/. Everything is
    # inspectable with no infrastructure beyond this machine.
    findings_dir: str = "local_findings"
    screenshots_dir: str = "screenshots/local"


SAFETY = SafetyConfig()
RUN = RunConfig()
