"""Render an executive PDF from the newest local_findings_adk/adk_run_*.json.

Usage:
    python adk_qa_pipeline/generate_pdf.py

Standalone (outside the ADK event loop), so sync Playwright is safe here.
"""

from __future__ import annotations

import base64
import io
import json
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from PIL import Image  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from adk_qa_pipeline.tools import page_slug  # noqa: E402

ARTIFACTS_DIR = _REPO_ROOT / "local_findings_adk"
SCREENSHOT_DIR = _REPO_ROOT / "screenshots" / "local"

MAX_EMBED_WIDTH = 900
SLICE_ASPECT = 1.45

SEV_ORDER = ["critical", "high", "medium", "low", "info"]
SEV_COLOR = {
    "critical": "#dc2626",
    "high": "#ea580c",
    "medium": "#d97706",
    "low": "#64748b",
    "info": "#0f766e",
}


def newest_log() -> Path:
    logs = sorted(ARTIFACTS_DIR.glob("adk_run_*.json"), key=lambda p: p.stat().st_mtime)
    if not logs:
        raise SystemExit("No adk_run_*.json found - run main.py first.")
    return logs[-1]


def img_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def slice_screenshot(path: Path) -> list[str]:
    """Chop a tall capture into page-sized chunks (base64 JPEGs).

    A full-page mobile capture can be 10k+ px tall; printing one image
    that spans many A4 pages makes Chromium's print tiler glitch into
    black bands. Slicing here means every <img> fits comfortably inside
    a single printed page.
    """
    im = Image.open(path).convert("RGB")
    if im.width > MAX_EMBED_WIDTH:
        ratio = MAX_EMBED_WIDTH / im.width
        im = im.resize((MAX_EMBED_WIDTH, int(im.height * ratio)),
                       Image.LANCZOS)
    slice_h = max(400, int(im.width / SLICE_ASPECT))
    chunks = []
    for top in range(0, im.height, slice_h):
        piece = im.crop((0, top, im.width, min(top + slice_h, im.height)))
        buf = io.BytesIO()
        piece.save(buf, format="JPEG", quality=82)
        chunks.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
    return chunks


def finding_card(f: dict) -> str:
    sev = f.get("severity", "info")
    color = SEV_COLOR.get(sev, "#64748b")
    tags = ", ".join(t for t in f.get("tags", [])[:4])
    detail = (f.get("detail") or "").replace("<", "&lt;")
    tool = f.get("source_tool", "")
    return f"""
    <div class="finding">
      <div class="row">
        <span class="chip" style="background:{color}">{sev.upper()}</span>
        <span class="title">{f.get('title', '')}</span>
        <span class="tool">{tool}</span>
      </div>
      <p class="detail">{detail}</p>
      <p class="tags">{tags}</p>
    </div>"""


def build_html(log: dict) -> str:
    meta = log.get("meta", {})
    target_url = meta.get("target_url", "")
    slug = page_slug(target_url)
    counts = log.get("severity_counts", {})
    risks = log.get("top_risks", [])
    findings = sorted(
        log.get("findings", []),
        key=lambda f: SEV_ORDER.index(f.get("severity", "info")),
    )
    shots = {}
    for name in ("mobile", "tablet", "desktop"):
        p = SCREENSHOT_DIR / f"{slug}_{name}.png"
        if p.exists():
            shots[name] = slice_screenshot(p)

    shot_html = ""
    for name, chunks in shots.items():
        total = len(chunks)
        for i, b64 in enumerate(chunks, 1):
            cap = (f"{name.capitalize()} breakpoint - automated capture "
                   f"(part {i}/{total})") if total > 1 else \
                  f"{name.capitalize()} breakpoint - automated capture"
            shot_html += (
                f'<figure><img src="data:image/jpeg;base64,{b64}"/>'
                f"<figcaption>{cap}</figcaption></figure>"
            )
    risk_html = "".join(f"<li>{r}</li>" for r in risks)
    cards = "".join(finding_card(f) for f in findings)
    generated = datetime.now().strftime("%B %d, %Y %H:%M")

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    @page {{ size: A4; margin: 18mm 14mm; }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #1f2937;
            font-size: 10.5pt; line-height: 1.45; }}
    .cover {{ background: #111827; color: #f9fafb; padding: 26px 30px;
              border-radius: 10px; margin-bottom: 20px; }}
    .cover h1 {{ margin: 0 0 6px; font-size: 21pt; }}
    .cover .sub {{ color: #9ca3af; font-size: 9.5pt; }}
    .kpis {{ display: flex; gap: 10px; margin: 16px 0 22px; }}
    .kpi {{ flex: 1; border: 1px solid #e5e7eb; border-radius: 8px;
            padding: 12px 14px; text-align: center; }}
    .kpi .num {{ font-size: 17pt; font-weight: 700; }}
    h2 {{ font-size: 13pt; border-bottom: 2px solid #111827;
          padding-bottom: 4px; margin-top: 24px; }}
    ul.risks li {{ margin-bottom: 5px; }}
    .finding {{ border: 1px solid #e5e7eb; border-left: 4px solid #ccc;
                border-radius: 6px; padding: 9px 12px; margin-bottom: 9px;
                page-break-inside: avoid; }}
    .row {{ display: flex; align-items: center; gap: 8px; }}
    .chip {{ color: #fff; font-size: 7pt; font-weight: 700; padding: 2px 8px;
             border-radius: 999px; letter-spacing: .04em; }}
    .title {{ font-weight: 600; font-size: 10pt; flex: 1; }}
    .tool {{ color: #6b7280; font-size: 7.5pt; font-style: italic; }}
    .detail {{ margin: 5px 0 3px; font-size: 9pt; color: #374151; }}
    .tags {{ margin: 0; font-size: 7.5pt; color: #9ca3af; }}
    figure {{ margin: 14px 0; page-break-inside: avoid; text-align: center; }}
    figure img {{ max-width: 100%; border: 1px solid #e5e7eb; }}
    figcaption {{ font-size: 8pt; color: #6b7280; margin-top: 4px; }}
    .safety {{ background: #f0fdf4; border: 1px solid #bbf7d0; color: #166534;
               border-radius: 8px; padding: 10px 14px; font-size: 8.5pt;
               margin-top: 22px; }}
    pre {{ background: #f3f4f6; border-radius: 6px; padding: 12px;
           font-size: 7.5pt; white-space: pre-wrap; word-break: break-word; }}
    </style></head><body>

    <div class="cover">
      <h1>ADK Multi-Agent QA Report</h1>
      <div class="sub">Target: {meta.get('target_url', '')}<br/>
      Generated {generated} &middot; Pipeline: google-adk supervisor + 4 specialists<br/>
      Elapsed: {meta.get('elapsed_seconds', '?')}s</div>
    </div>

    <div class="kpis">
      <div class="kpi"><div class="num">{len(findings)}</div>Total findings</div>
      <div class="kpi"><div class="num" style="color:#dc2626">{counts.get('critical', 0)}</div>Critical</div>
      <div class="kpi"><div class="num" style="color:#ea580c">{counts.get('high', 0)}</div>High</div>
      <div class="kpi"><div class="num" style="color:#d97706">{counts.get('medium', 0)}</div>Medium</div>
      <div class="kpi"><div class="num">{len(log.get('tool_runs', []))}</div>Tool runs OK</div>
    </div>

    <h2>Top Risks</h2>
    <ul class="risks">{''.join(f'<li>{r}</li>' for r in risks)}</ul>

    <h2>Evidence Captures</h2>
    {shot_html}

    <h2>All Findings ({len(findings)})</h2>
    {cards}

    <h2>Appendix: Supervisor Aggregate</h2>
    <pre>{json.dumps({'sections': json.loads(
        (log.get('supervisor_summary') or '{}').strip() or '{}'
    ).get('sections', 'see structured log')}, indent=1)[:1500]}</pre>

    <div class="safety">
      <b>Safety compliance:</b> robots.txt fail-closed enforced per tool call;
      honest contactable User-Agent on every request; 1.5s minimum delay between
      page loads; form submission blocked by guardrail callback + tool policy -
      validation state was inspected only, no data entered any live pipeline.
    </div>

    </body></html>"""


def main() -> None:
    log_path = newest_log()
    log = json.loads(log_path.read_text(encoding="utf-8"))
    target_url = log.get("meta", {}).get("target_url", "site")
    slug = page_slug(target_url).replace(".", "_")
    html = build_html(log)

    tmp_html = ARTIFACTS_DIR / "_report.html"
    tmp_html.write_text(html, encoding="utf-8")

    out_pdf = _REPO_ROOT / f"ADK-QA-Report_{slug}.pdf"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(tmp_html.as_uri(), wait_until="load")
        page.wait_for_timeout(500)
        page.pdf(path=str(out_pdf), format="A4",
                 margin={"top": "16mm", "bottom": "16mm",
                         "left": "13mm", "right": "13mm"},
                 print_background=True)
        browser.close()

    print(f"PDF written: {out_pdf}")


if __name__ == "__main__":
    main()
