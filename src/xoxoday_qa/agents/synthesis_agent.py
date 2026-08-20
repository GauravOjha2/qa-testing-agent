"""Synthesis agent — runs after the scan completes.

Reads all findings from ./local_findings/, dedupes near-identical
findings across pages (e.g. the same axe-core violation firing on every
page because of a shared nav component), ranks by severity, and renders
the final report.
"""

from __future__ import annotations

import time
from collections import defaultdict

from ..models import Severity
from ..store import load_all_results

_SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]
_SEVERITY_RANK = {s: i for i, s in enumerate(_SEVERITY_ORDER)}


def load_findings() -> list[dict]:
    findings = []
    for r in load_all_results():
        for f in r.get("findings", []):
            f = dict(f)
            f.setdefault("url", r.get("url"))
            findings.append(f)
    return findings


def dedupe(findings: list[dict]) -> list[dict]:
    """Collapse findings with the same (title, agent) into one entry with
    an affected-URL list, when they recur across many pages — this is what
    keeps a shared-component bug from flooding the report as 200 rows.
    """
    grouped: dict[tuple[str, str], dict] = {}
    for f in findings:
        key = (f.get("agent", ""), f.get("title", ""))
        if key not in grouped:
            grouped[key] = {**f, "affected_urls": [f.get("url")]}
        else:
            if f.get("url") not in grouped[key]["affected_urls"]:
                grouped[key]["affected_urls"].append(f.get("url"))
    return list(grouped.values())


def rank(findings: list[dict]) -> list[dict]:
    return sorted(
        findings,
        key=lambda f: (_SEVERITY_RANK.get(Severity(f.get("severity", "info")), 99), -len(f.get("affected_urls", [1]))),
    )


def summarize(findings: list[dict]) -> dict:
    by_severity = defaultdict(int)
    by_agent = defaultdict(int)
    pages_affected: set[str] = set()

    for f in findings:
        by_severity[f.get("severity", "info")] += 1
        by_agent[f.get("agent", "unknown")] += 1
        pages_affected.update(f.get("affected_urls", []))

    return {
        "total_findings": len(findings),
        "by_severity": dict(by_severity),
        "by_agent": dict(by_agent),
        "pages_affected": len(pages_affected),
    }


def render_html_report(findings: list[dict], summary: dict, run_seconds: float, pages_tested: int) -> str:
    rows = []
    for f in findings:
        if f.get("severity") == "info":
            continue  # info/pass findings go in an appendix, not the headline table
        urls_html = "<br>".join(f"<a href='{u}'>{u}</a>" for u in f.get("affected_urls", [])[:5])
        rows.append(f"""
        <tr class="sev-{f.get('severity')}">
            <td>{f.get('severity', '').upper()}</td>
            <td>{f.get('agent', '')}</td>
            <td>{f.get('title', '')}</td>
            <td>{f.get('detail', '')[:300]}</td>
            <td>{urls_html}</td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Xoxoday QA Agent Report</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 1100px; margin: 40px auto; color: #1a1a1a; }}
h1 {{ margin-bottom: 4px; }}
.meta {{ color: #666; margin-bottom: 24px; }}
.summary {{ display: flex; gap: 24px; margin-bottom: 32px; }}
.stat {{ background: #f5f5f5; padding: 16px 20px; border-radius: 8px; }}
.stat .n {{ font-size: 28px; font-weight: 700; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; font-size: 14px; vertical-align: top; }}
th {{ background: #fafafa; }}
.sev-critical {{ border-left: 4px solid #d32f2f; }}
.sev-high {{ border-left: 4px solid #f57c00; }}
.sev-medium {{ border-left: 4px solid #fbc02d; }}
.sev-low {{ border-left: 4px solid #9e9e9e; }}
</style></head>
<body>
<h1>Xoxoday QA Agent — Findings Report</h1>
<div class="meta">Pages tested: {pages_tested} · Run time: {run_seconds/60:.1f} min · Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}</div>
<div class="summary">
  <div class="stat"><div class="n">{summary['total_findings']}</div>issues found</div>
  <div class="stat"><div class="n">{summary['pages_affected']}</div>pages affected</div>
  <div class="stat"><div class="n">{summary['by_severity'].get('critical', 0)}</div>critical</div>
  <div class="stat"><div class="n">{summary['by_severity'].get('high', 0)}</div>high</div>
</div>
<table>
<tr><th>Severity</th><th>Agent</th><th>Finding</th><th>Detail</th><th>Affected pages</th></tr>
{''.join(rows)}
</table>
</body></html>"""


def run(run_seconds: float = 0.0, pages_tested: int = 0, out_path: str = "report.html") -> str:
    raw = load_findings()
    deduped = dedupe(raw)
    ranked = rank(deduped)
    summary = summarize(deduped)

    html = render_html_report(ranked, summary, run_seconds, pages_tested)
    with open(out_path, "w") as f:
        f.write(html)

    return out_path


if __name__ == "__main__":
    import json
    path = run()
    print(f"Report written to {path}")
