"""Data models for scan results. Pydantic keeps findings structured,
JSON-serializable, and reproducible end-to-end."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low", "info"]
Category = Literal[
    "accessibility", "performance", "forms", "visual", "geo_aeo", "technical"
]


def finding_id(category: str, rule: str, *parts: str) -> str:
    """Deterministic ID: same input always yields the same finding id,
    which is what makes dedup and re-runs reproducible."""
    raw = "|".join([category, rule, *parts])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class Finding(BaseModel):
    id: str
    category: Category
    severity: Severity
    title: str
    detail: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    recommendation: str = ""

    @property
    def dedup_key(self) -> str:
        selector = str(self.evidence.get("selector", ""))
        return finding_id(self.category, self.title, selector)


class ScreenshotMeta(BaseModel):
    viewport: str
    path: str            # repo-relative png
    thumb: str           # repo-relative jpeg thumbnail
    width: int
    height: int
    overflow_x: bool = False
    overflow_px: int = 0


class StageResult(BaseModel):
    key: str
    label: str
    status: Literal["ok", "degraded", "failed"]
    elapsed_seconds: float
    detail: str = ""


class ScanResult(BaseModel):
    scan_id: str
    target_url: str
    final_url: str = ""
    scanned_at: str
    elapsed_seconds: float = 0.0
    user_agent: str
    model: str
    severity_counts: dict[str, int] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    top_risks: list[str] = Field(default_factory=list)
    executive_summary: str = ""
    screenshots: list[ScreenshotMeta] = Field(default_factory=list)
    vitals: dict[str, Any] = Field(default_factory=dict)
    stages: list[StageResult] = Field(default_factory=list)
    safety: dict[str, Any] = Field(default_factory=dict)


def dedup_findings(findings: list[Finding]) -> list[Finding]:
    """Collapse identical findings, keep stable severity-sorted order."""
    seen: set[str] = set()
    unique: list[Finding] = []
    for f in findings:
        if f.dedup_key in seen:
            continue
        seen.add(f.dedup_key)
        unique.append(f)
    order = {s: i for i, s in enumerate(["critical", "high", "medium", "low", "info"])}
    unique.sort(key=lambda f: (order.get(f.severity, 9), f.category, f.title))
    return unique


def severity_counts(findings: list[Finding]) -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts
