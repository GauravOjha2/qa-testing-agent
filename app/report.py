"""A4 PDF report renderer.

The pipeline emits structured JSON; this module turns that JSON into a
print-quality A4 PDF. Composition is HTML + CSS (dark cover, KPI cards,
severity-coloured finding cards, embedded evidence screenshots, safety
statement) printed by headless Chromium via Playwright's page.pdf().
Pillow produced the JPEG thumbnails that get embedded, which keeps the
PDF small and the render fast and deterministic.
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from . import config
from .models import Finding, ScanResult

SEV_COLOR = {
    "critical": "#ff4d4d",
    "high": "#ff8c42",
    "medium": "#ffd166",
    "low": "#7dd3fc",
    "info": "#94a3b8",
}
SEV_ORDER = ["critical", "high", "medium", "low", "info"]


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _finding_card(f: Finding, index: int) -> str:
    color = SEV_COLOR.get(f.severity, "#94a3b8")
    evidence_rows = "".join(
        f'<div class="ev-row"><span class="ev-key">{_esc(k)}</span>'
        f'<span class="ev-val">{_esc(str(v)[:300])}</span></div>'
        for k, v in list(f.evidence.items())[:6]
        if str(v).strip()
    )
    return f"""
    <div class="card">
      <div class="card-bar" style="background:{color}"></div>
      <div class="card-body">
        <div class="card-head">
          <span class="chip" style="background:{color}1a;color:{color};border-color:{color}55">{f.severity.upper()}</span>
          <span class="chip chip-ghost">{_esc(f.category)}</span>
          <span class="fid">#{index:03d} · {_esc(f.id)}</span>
        </div>
        <h3>{_esc(f.title)}</h3>
        <p class="detail">{_esc(f.detail)}</p>
        {f'<div class="evidence"><div class="ev-title">Evidence</div>{evidence_rows}</div>' if evidence_rows else ''}
        {f'<p class="rec"><strong>Fix:</strong> {_esc(f.recommendation)}</p>' if f.recommendation else ''}
      </div>
    </div>"""


def _kpi(value: Any, label: str, color: str) -> str:
    return (
        f'<div class="kpi"><div class="kpi-num" style="color:{color}">{_esc(value)}</div>'
        f'<div class="kpi-label">{_esc(label)}</div></div>'
    )


def _vitals_table(vitals: dict[str, Any]) -> str:
    if not vitals:
        return '<p class="muted">Core Web Vitals could not be measured for this run.</p>'
    rows = [
        ("LCP", "lcp_ms", "ms"), ("CLS", "cls", ""), ("INP", "inp_ms", "ms"),
        ("TBT (lab proxy)", "tbt_ms", "ms"), ("FCP", "fcp_ms", "ms"),
        ("Performance score", "performance_score", ""),
    ]
    body = ""
    for label, key, unit in rows:
        value = vitals.get(key)
        if value is None:
            continue
        shown = f"{value:.2f}" if isinstance(value, float) and unit == "" else f"{value:g}"
        body += f"<tr><td>{_esc(label)}</td><td class='mono'>{_esc(shown)}{_esc(unit)}</td></tr>"
    note = vitals.get("inp_note", "")
    return (
        f'<table class="tbl"><thead><tr><th>Metric</th><th>Value</th></tr></thead>'
        f"<tbody>{body}</tbody></table>"
        f'<p class="muted">Source: {_esc(vitals.get("source", "n/a"))}. {_esc(note)}</p>'
    )


def _stages_table(result: ScanResult) -> str:
    rows = "".join(
        f"<tr><td>{_esc(s.label)}</td><td class='mono'>{_esc(s.status)}</td>"
        f"<td class='mono'>{s.elapsed_seconds:g}s</td><td class='muted'>{_esc(s.detail)}</td></tr>"
        for s in result.stages
    )
    return (
        '<table class="tbl"><thead><tr><th>Stage</th><th>Status</th><th>Time</th><th>Detail</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def _gallery(result: ScanResult) -> str:
    cards = []
    for shot in result.screenshots:
        path = config.REPO_ROOT / shot.thumb
        if not path.is_file():
            continue
        overflow = (
            f'<span class="chip" style="background:#ff8c421a;color:#ff8c42;border-color:#ff8c4255">'
            f"overflow +{shot.overflow_px}px</span>"
            if shot.overflow_x
            else '<span class="chip" style="background:#34d3991a;color:#34d399;border-color:#34d39955">no overflow</span>'
        )
        cards.append(
            f'<figure class="shot"><img src="data:image/jpeg;base64,{_b64(path)}" alt="{_esc(shot.viewport)} capture"/>'
            f"<figcaption><strong>{_esc(shot.viewport)}</strong> · {shot.width}×{shot.height}px {overflow}</figcaption></figure>"
        )
    if not cards:
        return '<p class="muted">No screenshots were captured in this run.</p>'
    return f'<div class="gallery">{"".join(cards)}</div>'


def build_html(result: ScanResult) -> str:
    counts = result.severity_counts
    total = sum(counts.values())
    grouped: dict[str, list[Finding]] = {s: [] for s in SEV_ORDER}
    for f in result.findings:
        grouped.setdefault(f.severity, []).append(f)
    finding_html = "".join(
        _finding_card(f, i)
        for i, f in enumerate(result.findings, start=1)
    ) or '<p class="muted">No findings were recorded for this target.</p>'
    a11y_rules = sum(1 for f in result.findings if f.category == "accessibility")
    top_risks = "".join(f"<li>{_esc(r)}</li>" for r in result.top_risks) or "<li>No material risks.</li>"
    safety = result.safety

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<title>SiteSentinel QA Report — {_esc(result.final_url or result.target_url)}</title>
<style>
  @page {{ size: A4; margin: 14mm 13mm; }}
  @page cover {{ size: A4; margin: 0; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin:0; padding:0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
                color:#0f172a; font-size:10.5pt; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  h1,h2,h3 {{ margin:0; line-height:1.25; }}
  .mono {{ font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; }}
  .muted {{ color:#64748b; font-size:9pt; }}

  /* ---------- cover ---------- */
  .cover {{ page: cover; width:210mm; height:297mm; padding:24mm 20mm;
            background:linear-gradient(150deg,#05070d 0%,#0b1220 45%,#0d1a2f 100%);
            color:#e6edf7; page-break-after:always; position:relative; }}
  .cover .brand {{ display:flex; align-items:center; gap:10px; font-weight:700; letter-spacing:.14em;
                   text-transform:uppercase; font-size:9pt; color:#7dd3fc; }}
  .cover .dot {{ width:9px; height:9px; border-radius:50%; background:linear-gradient(135deg,#38bdf8,#818cf8); }}
  .cover h1 {{ font-size:34pt; margin-top:16mm; letter-spacing:-.02em; }}
  /* Solid brand colour, not a gradient clip: background-clip:text is
     unreliable in Chromium's PDF print path and renders as a filled box. */
  .cover h1 span {{ color:#7dd3fc; }}
  .cover .url {{ margin-top:6mm; font-size:11pt; color:#94a3b8; word-break:break-all; }}
  .cover .meta {{ margin-top:4mm; font-size:9.5pt; color:#64748b; }}
  .cover .kpis {{ display:flex; gap:5mm; margin-top:16mm; }}
  .kpi {{ flex:1; background:rgba(148,163,184,.10); border:1px solid rgba(148,163,184,.22);
          border-radius:4mm; padding:6mm 4mm; }}
  .kpi-num {{ font-size:24pt; font-weight:800; }}
  .kpi-label {{ font-size:8pt; text-transform:uppercase; letter-spacing:.10em; color:#94a3b8; margin-top:1.5mm; }}
  .cover .scope {{ margin-top:12mm; background:rgba(148,163,184,.08); border:1px solid rgba(148,163,184,.2);
                    border-radius:4mm; padding:6mm; font-size:9.5pt; color:#cbd5e1; }}
  .cover .scope-title {{ font-size:8pt; text-transform:uppercase; letter-spacing:.14em; color:#7dd3fc; margin-bottom:3mm; }}
  .cover .scope ul {{ margin:0; padding-left:5mm; line-height:1.75; }}
  .cover .scope strong {{ color:#e6edf7; }}
  .cover .rules {{ position:absolute; left:20mm; right:20mm; bottom:22mm; font-size:8.5pt; color:#64748b;
                   border-top:1px solid rgba(148,163,184,.25); padding-top:4mm; line-height:1.6; }}

  /* ---------- body sections ---------- */
  section {{ page-break-before:always; }}
  section:first-of-type {{ page-break-before:auto; }}
  h2 {{ font-size:15pt; margin-bottom:4mm; padding-bottom:2mm; border-bottom:2px solid #e2e8f0; }}
  h2 .n {{ color:#94a3b8; font-weight:600; margin-right:2mm; }}
  .summary {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:3mm; padding:5mm; line-height:1.65; }}
  ul.risks {{ margin:4mm 0 0; padding-left:6mm; line-height:1.7; }}
  .tbl {{ width:100%; border-collapse:collapse; margin-top:3mm; }}
  .tbl th {{ text-align:left; font-size:8pt; text-transform:uppercase; letter-spacing:.08em;
             color:#64748b; border-bottom:1px solid #e2e8f0; padding:2mm 2mm; }}
  .tbl td {{ padding:2mm; border-bottom:1px solid #f1f5f9; vertical-align:top; }}

  .card {{ display:flex; border:1px solid #e2e8f0; border-radius:3mm; overflow:hidden;
           margin-bottom:4mm; page-break-inside:avoid; }}
  .card-bar {{ width:2.5mm; }}
  .card-body {{ padding:4mm 5mm; flex:1; }}
  .card-head {{ display:flex; align-items:center; gap:2mm; margin-bottom:2mm; }}
  .chip {{ font-size:7.5pt; font-weight:700; letter-spacing:.06em; border:1px solid; border-radius:2mm;
           padding:.8mm 2mm; }}
  .chip-ghost {{ color:#475569; border-color:#cbd5e1; background:#f8fafc; }}
  .fid {{ margin-left:auto; font-size:7.5pt; color:#94a3b8; }}
  .card h3 {{ font-size:11pt; }}
  .detail {{ margin:2mm 0 0; line-height:1.55; color:#334155; }}
  .evidence {{ margin-top:3mm; background:#0b1220; border-radius:2mm; padding:3mm; }}
  .ev-title {{ font-size:7.5pt; text-transform:uppercase; letter-spacing:.1em; color:#7dd3fc; margin-bottom:1.5mm; }}
  .ev-row {{ display:flex; gap:3mm; font-size:8.5pt; color:#cbd5e1; line-height:1.5; }}
  .ev-key {{ color:#818cf8; min-width:32mm; font-family:Consolas, monospace; }}
  .ev-val {{ flex:1; word-break:break-word; font-family:Consolas, monospace; }}
  .rec {{ margin:3mm 0 0; font-size:9.5pt; color:#0f172a; }}

  .gallery {{ display:grid; grid-template-columns:1fr 1fr; gap:4mm; }}
  .shot {{ margin:0; border:1px solid #e2e8f0; border-radius:3mm; overflow:hidden; page-break-inside:avoid; }}
  .shot img {{ width:100%; display:block; }}
  .shot figcaption {{ padding:2mm 3mm; font-size:8.5pt; background:#f8fafc; border-top:1px solid #e2e8f0; }}
  .safety {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:3mm; padding:5mm; line-height:1.7; }}
  .safety code {{ background:#e2e8f0; padding:.3mm 1.2mm; border-radius:1mm; font-size:8.5pt; }}
</style></head>
<body>
  <div class="cover">
    <div class="brand"><span class="dot"></span> SiteSentinel · Website QA &amp; Vulnerability Report</div>
    <h1>Website <span>Quality &amp; Risk</span><br/>Assessment</h1>
    <div class="url">{_esc(result.final_url or result.target_url)}</div>
    <div class="meta">Scanned {_esc(result.scanned_at)} · {result.elapsed_seconds:g}s · engine {_esc(result.model)}</div>
    <div class="kpis">
      {_kpi(counts.get('critical', 0), 'Critical', SEV_COLOR['critical'])}
      {_kpi(counts.get('high', 0), 'High', SEV_COLOR['high'])}
      {_kpi(counts.get('medium', 0), 'Medium', SEV_COLOR['medium'])}
      {_kpi(total, 'Total findings', '#e6edf7')}
    </div>
    <div class="scope">
      <div class="scope-title">What was checked</div>
      <ul>
        <li><strong>Responsive captures</strong> — full-page mobile 390, tablet 768, desktop 1440 + horizontal-overflow probe</li>
        <li><strong>Accessibility</strong> — axe-core against WCAG 2.2 A/AA, {a11y_rules} violation rules flagged</li>
        <li><strong>Core Web Vitals</strong> — LCP / CLS / INP measured on a mobile profile</li>
        <li><strong>Form safety</strong> — boundary, invalid and i18n probes; validation state read, never submitted</li>
        <li><strong>AI-answer readiness</strong> — GEO/AEO ground-truth review on {_esc(result.model)}</li>
      </ul>
    </div>
    <div class="rules">
      robots.txt respected (fail-closed) · {config.THROTTLE_SECONDS:g}s throttle · honest User-Agent<br/>
      Forms never submitted — no submit code path exists · no data leaves this scan<br/>
      All AI analysis on <strong>{_esc(result.model)}</strong> · findings deduplicated &amp; reproducible
    </div>
  </div>

  <section>
    <h2><span class="n">01</span>Executive summary</h2>
    <div class="summary">{_esc(result.executive_summary)}</div>
    <h2 style="margin-top:8mm"><span class="n">02</span>Top risks</h2>
    <ul class="risks">{top_risks}</ul>
  </section>

  <section>
    <h2><span class="n">03</span>Core Web Vitals</h2>
    {_vitals_table(result.vitals)}
    <h2 style="margin-top:8mm"><span class="n">04</span>Scan stages</h2>
    {_stages_table(result)}
  </section>

  <section>
    <h2><span class="n">05</span>Findings ({total})</h2>
    {finding_html}
  </section>

  <section>
    <h2><span class="n">06</span>Evidence — captures</h2>
    {_gallery(result)}
  </section>

  <section>
    <h2><span class="n">07</span>Safety &amp; compliance statement</h2>
    <div class="safety">
      <p><strong>Authorisation.</strong> The scanner fetched <code>{_esc(safety.get('robots_url', ''))}</code>
      before any page load and confirmed it permits this bot: {_esc(safety.get('robots_txt', ''))}.
      If robots.txt is unreachable the scan fails closed rather than proceeding.</p>
      <p><strong>Politeness.</strong> Requests to the target origin are throttled to one every
      {config.THROTTLE_SECONDS:g}s. User-Agent: <code>{_esc(safety.get('user_agent', ''))}</code> — honest and contactable.</p>
      <p><strong>Form safety.</strong> {_esc(safety.get('forms_policy', ''))}
      Recorded submissions in this run: <strong>{_esc(safety.get('forms_submitted', 0))}</strong>.</p>
      <p><strong>Data handling.</strong> No scan data is submitted to any third party; artifacts stay on the scan host
      and expire after {config.JOB_TTL_SECONDS // 3600} hours.</p>
      <p><strong>AI layer.</strong> {_esc(safety.get('ai_model_policy', ''))} Model used: <code>{_esc(safety.get('ai_model', ''))}</code>.</p>
      <p><strong>Reproducibility.</strong> Findings carry deterministic IDs derived from rule + selector;
      duplicate observations are collapsed, so two runs against an unchanged page produce the same finding set.</p>
    </div>
    <p class="muted" style="margin-top:6mm">Generated by SiteSentinel · {_esc(result.scanned_at)} · scan id {_esc(result.scan_id)}</p>
  </section>
</body></html>"""


async def render_pdf(result: ScanResult, run_dir: Path, log) -> Path:
    html_doc = build_html(result)
    (run_dir / "report.html").write_text(html_doc, encoding="utf-8")
    pdf_path = run_dir / "report.pdf"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = await browser.new_page()
            await page.set_content(html_doc, wait_until="load")
            await page.emulate_media(media="print")
            await page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
            )
        finally:
            await browser.close()
    return pdf_path
