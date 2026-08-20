"""Shared data models for the Xoxoday QA agent system.

Every specialist agent (visual, forms, GEO/AEO, a11y+perf) emits Finding
objects in this shape so the synthesis agent can dedupe/rank/report over a
single uniform schema, regardless of which agent produced them.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    CRITICAL = "critical"   # broken conversion path, form submits garbage, page 500s
    HIGH = "high"            # visible layout break, wrong factual claim to AI engines
    MEDIUM = "medium"        # a11y violation, minor overflow, slow LCP
    LOW = "low"              # cosmetic nit, informational
    INFO = "info"            # passed check, logged for completeness / dashboards


class AgentSource(str, Enum):
    VISUAL_QA = "visual_qa"
    FORMS = "forms"
    GEO_AEO = "geo_aeo"
    A11Y_PERF = "a11y_perf"


class PageType(str, Enum):
    HOMEPAGE = "homepage"
    PRODUCT = "product"           # Empuls / Plum / Compass
    PRICING_ROI = "pricing_roi"
    INDUSTRY_LANDING = "industry_landing"
    BLOG = "blog"
    LOCALIZED = "localized"       # non-English variant of any of the above
    DEMO_FORM = "demo_form"       # Request a Demo / Talk to Sales
    OTHER = "other"


@dataclass
class PageTarget:
    """One URL to be tested, with metadata used for routing/prioritization."""

    url: str
    page_type: PageType = PageType.OTHER
    locale: str = "en"
    priority: int = 5  # 1 = highest; used to pick the demo subset (15-25 pages)


@dataclass
class Finding:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    url: str = ""
    agent: AgentSource = AgentSource.A11Y_PERF
    severity: Severity = Severity.INFO
    title: str = ""
    detail: str = ""
    evidence_uri: Optional[str] = None   # screenshot / trace path on disk
    confidence: float = 1.0              # 0-1, esp. for vision-judge / GEO diffs
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    raw: dict[str, Any] = field(default_factory=dict)  # agent-specific extra data

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["agent"] = self.agent.value
        d["severity"] = self.severity.value
        return d


@dataclass
class PageResult:
    url: str
    findings: list[Finding] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    network_failures: list[dict[str, Any]] = field(default_factory=list)
    tested_at: float = field(default_factory=time.time)
    error: Optional[str] = None  # set if the page itself couldn't be tested
