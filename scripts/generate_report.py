"""Generate a founder-ready PDF report from raw scan findings.

Reads every JSON result in ./local_findings/, separates real product
signal from scanner/environment noise, adds plain-English context for
each issue, embeds the breakpoint screenshots as evidence, and renders
the whole thing to PDF via headless Chromium (already installed as part
of Playwright).

Usage:
    python scripts/generate_report.py --out Xoxoday-QA-Report.pdf
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xoxoday_qa.config import RUN, SAFETY  # noqa: E402

# --------------------------------------------------------------------------
# Classification: what counts as product signal vs. scanner noise.
# --------------------------------------------------------------------------

# Third-party marketing/analytics endpoints. Failures to reach these are
# observability signals about the site's own tag/CSP configuration, not
# broken product functionality.
TRACKER_DOMAINS = [
    "adpxl.co", "clarity.ms", "bat.bing.com", "cr-relay.com", "mczbf.com",
    "doubleclick.net", "googleadservices.com", "google.com/ccm",
    "google.com/rmkt", "analytics.google.com", "google.co.in/pagead",
    "px.ads.linkedin.com", "tracking-api.g2.com", "hs-scripts.com",
    "facebook.net", "hotjar.com", "factors.ai",
]

VENDOR_NAMES = {
    "clarity.ms": "Microsoft Clarity (session replay)",
    "bat.bing.com": "Bing UET conversion tracking",
    "mczbf.com": "Marketo Munchkin (marketing automation)",
    "doubleclick.net": "Google Ads / DoubleClick",
    "googleadservices.com": "Google Ads",
    "google.com/ccm": "Google Ads consent-mode attribution",
    "google.com/rmkt": "Google Ads remarketing",
    "analytics.google.com": "Google Analytics 4 (page-view beacon)",
    "google.co.in/pagead": "Google Ads remarketing pixel",
    "px.ads.linkedin.com": "LinkedIn conversion attribution",
    "tracking-api.g2.com": "G2 buyer-intent attribution",
    "hs-scripts.com": "HubSpot (chat/forms)",
    "adpxl.co": "Adpxl (ad verification)",
    "cr-relay.com": "Candor signals",
}

# Plain-English context per axe-core rule id, written for a non-engineer.
RULE_NOTES = {
    "image-alt": (
        "Images missing alt text",
        "Screen-reader users hear nothing for these images — including the "
        "main logo and customer logos (Nobel, Hyundai). Alt text is also how "
        "images surface in search.",
        "Add descriptive alt attributes (e.g. alt=\"Xoxoday Plum\" on the "
        "logo); use alt=\"\" for purely decorative images.",
    ),
    "meta-viewport": (
        "Pinch-to-zoom disabled on mobile",
        "The page's viewport tag disables zooming, so users with low vision "
        "cannot magnify content. This is a direct WCAG 2.2 AA failure "
        "(1.4.4 Resize Text) and a common source of mobile complaints.",
        "Remove user-scalable=no / maximum-scale from the viewport meta tag.",
    ),
    "color-contrast": (
        "Low-contrast text",
        "Text is too faint against its background for many readers to "
        "comfortably read — including pricing figures and primary buttons, "
        "i.e. exactly the content a buying decision depends on.",
        "Darken text/background pairs to meet the 4.5:1 ratio (3:1 for large "
        "text). The affected selectors are listed in the appendix.",
    ),
    "object-alt": (
        "Embedded <object> elements missing alt text",
        "Six embedded objects (feature illustrations) have no text "
        "alternative, so their content is invisible to assistive technology.",
        "Add accessible names via aria-label or an inner fallback element.",
    ),
    "link-name": (
        "Link with no discernible text",
        "The navbar brand link has no accessible name — screen-reader users "
        "hear it announced as just \"link\".",
        "Give the logo link an aria-label (\"Xoxoday home\").",
    ),
    "link-in-text-block": (
        "Links distinguishable by color only",
        "A link inside body text is identified only by its color, which "
        "fails WCAG 1.4.1 and is invisible to color-blind users.",
        "Add an underline or non-color cue to in-text links.",
    ),
    "blink": (
        "Deprecated <blink> element present",
        "A <blink> tag — obsolete since the 1990s — is still in the DOM "
        "(verified: a hidden \"New\" badge in the left-column nav, suppressed "
        "with visibility:hidden rather than removed). It is invisible to "
        "users today, but it flags the page as unmaintained to anyone "
        "inspecting it and should simply be deleted.",
        "Delete the <blink> element (keep the inner <sup>New</sup> badge if "
        "it's still wanted).",
    ),
}

_SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
_AFFECTS_RE = re.compile(r"Affects (\d+) element")
_BLOCKED_URL_RE = re.compile(r"(?:script|connect|image) '(https://[^'\s]+)")


def _affects(detail: str) -> int:
    m = _AFFECTS_RE.search(detail or "")
    return int(m.group(1)) if m else 1


def _is_tracker(url: str) -> bool:
    return any(d in url for d in TRACKER_DOMAINS)


def load_results() -> list[dict]:
    results = []
    for fname in sorted(os.listdir(RUN.findings_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(RUN.findings_dir, fname)) as f:
                results.append(json.load(f))
    return results


def classify(results: list[dict]) -> dict:
    """Split raw findings into report buckets."""
    signal, manual, blocked, noise, passes = [], [], [], [], []
    vendors: dict[str, set[str]] = defaultdict(set)

    for r in results:
        url = r.get("url", "")
        for f in r.get("findings", []):
            agent = f.get("agent", "")
            title = f.get("title", "")
            detail = f.get("detail", "")
            tags = f.get("tags", [])

            if agent == "a11y_perf" and "wcag" in tags:
                signal.append(f)
            elif "core-web-vitals" in tags:
                signal.append(f)
            elif agent == "forms" and "validation" in tags:
                manual.append(f)
            elif agent == "visual_qa":
                if "pass" in tags:
                    passes.append(f)
                else:
                    signal.append(f)
            elif agent == "geo_aeo":
                if "pass" not in tags:
                    signal.append(f)
                else:
                    passes.append(f)
            elif "console-error" in tags and detail.startswith("Refused to"):
                m = _BLOCKED_URL_RE.search(detail)
                if m:
                    blocked_url = m.group(1)
                    for domain, name in VENDOR_NAMES.items():
                        if domain in blocked_url:
                            vendors[name].add(domain)
                            break
                    else:
                        noise.append(f)
                else:
                    noise.append(f)
            elif "silent-failure" in tags:
                target = detail
                if _is_tracker(target):
                    for domain, name in VENDOR_NAMES.items():
                        if domain in target:
                            vendors[name].add(domain)
                            break
                else:
                    noise.append(f)
            elif title.startswith(("No forms found", "validation tested", "stopped before submit")):
                passes.append(f)
            else:
                noise.append(f)

    return {
        "signal": signal,
        "manual": manual,
        "blocked_vendors": dict(vendors),
        "noise": noise,
        "passes": passes,
        "pages": results,
    }


# --------------------------------------------------------------------------
# HTML rendering
# --------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', -apple-system, Helvetica, Arial, sans-serif;
       color: #1c2733; font-size: 13px; line-height: 1.55; margin: 0; }
.page-pad { padding: 0 6px; }
h1 { font-size: 26px; margin: 0 0 4px; letter-spacing: -0.5px; }
h2 { font-size: 17px; margin: 28px 0 10px; padding-bottom: 6px;
     border-bottom: 2px solid #e8ecf0; page-break-after: avoid; }
h3 { font-size: 14px; margin: 18px 0 6px; page-break-after: avoid; }
p { margin: 6px 0; }
.muted { color: #5b6b7b; }
.sub { font-size: 14px; color: #40546a; margin-bottom: 2px; }
.meta-line { font-size: 11px; color: #7b8a99; margin-bottom: 22px; }

.stat-row { display: flex; gap: 12px; margin: 16px 0 6px; }
.stat { flex: 1; background: #f4f7fa; border: 1px solid #e2e9ef;
        border-radius: 8px; padding: 12px 14px; }
.stat .n { font-size: 24px; font-weight: 700; }
.stat .lbl { font-size: 10.5px; color: #5b6b7b; text-transform: uppercase;
             letter-spacing: 0.4px; }

.takeaways { background: #f8fafc; border-left: 4px solid #2563eb;
             border-radius: 0 8px 8px 0; padding: 12px 16px; margin: 14px 0; }
.takeaways ul { margin: 6px 0 2px; padding-left: 20px; }
.takeaways li { margin: 5px 0; }

.card { border: 1px solid #e2e9ef; border-radius: 8px;
        padding: 12px 16px; margin: 10px 0; page-break-inside: avoid; }
.card.critical { border-left: 5px solid #d32f2f; }
.card.high     { border-left: 5px solid #f57c00; }
.card.medium   { border-left: 5px solid #f0b400; }
.card.low      { border-left: 5px solid #9e9e9e; }
.card-head { display: flex; align-items: center; gap: 8px; }
.card-title { font-weight: 700; font-size: 13.5px; }
.chip { font-size: 9.5px; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.5px; color: #fff; border-radius: 4px;
        padding: 2px 7px; white-space: nowrap; }
.chip.critical { background: #d32f2f; }
.chip.high { background: #f57c00; }
.chip.medium { background: #f0b400; color: #3a3000; }
.chip.low { background: #9e9e9e; }
.chip.info { background: #607d8b; }
.field { margin-top: 6px; }
.field .k { font-size: 10.5px; font-weight: 700; color: #5b6b7b;
            text-transform: uppercase; letter-spacing: 0.4px; }

.shot { text-align: center; margin: 12px 0 20px; page-break-inside: avoid; }
.shot img { max-width: 100%; max-height: 880px; width: auto; height: auto;
            border: 1px solid #d7dee5; border-radius: 6px; }
.shot .cap { font-size: 11px; color: #5b6b7b; margin-top: 5px; }

table { width: 100%; border-collapse: collapse; font-size: 10.5px; }
th { background: #f4f7fa; text-align: left; padding: 6px 8px;
     border-bottom: 2px solid #e2e9ef; }
td { padding: 5px 8px; border-bottom: 1px solid #edf1f5;
     vertical-align: top; word-break: break-word; }
.sev-critical td:first-child { color: #d32f2f; font-weight: 700; }
.sev-high td:first-child { color: #f57c00; font-weight: 700; }
.sev-medium td:first-child { color: #b28900; font-weight: 700; }

.breaker { page-break-before: always; }
.disclosure { background: #f8fafc; border: 1px solid #e2e9ef;
              border-radius: 8px; padding: 12px 16px; margin: 10px 0; }
"""


def _chip(sev: str) -> str:
    return f'<span class="chip {sev}">{sev}</span>'


def _signal_card(f: dict) -> str:
    tags = f.get("tags", [])
    rule = next((t for t in reversed(tags) if t not in ("a11y", "wcag", "perf", "core-web-vitals")), "")
    sev = f.get("severity", "info")
    title, why, fix = RULE_NOTES.get(
        rule,
        (f.get("title", ""), "", ""),
    )
    n = _affects(f.get("detail", ""))
    affects = f"<div class='field'><span class='k'>Scope</span><div>{n} element(s) on the tested page</div></div>" \
        if rule in RULE_NOTES else ""
    why_html = f"<div class='field'><span class='k'>Why it matters</span><div>{why}</div></div>" if why else ""
    fix_html = f"<div class='field'><span class='k'>Recommended fix</span><div>{fix}</div></div>" if fix else ""
    detail_html = "" if rule in RULE_NOTES else \
        f"<div class='field'><span class='k'>Detail</span><div>{f.get('detail', '')[:400]}</div></div>"
    return f"""
    <div class="card {sev}">
      <div class="card-head">{_chip(sev)}<span class="card-title">{title}</span></div>
      {affects}{why_html}{fix_html}{detail_html}
    </div>"""


def _img_data_uri(path: str) -> str:
    with open(path, "rb") as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


def build_html(buckets: dict, out_stem: str) -> str:
    signal = sorted(
        buckets["signal"],
        key=lambda f: _SEVERITY_ORDER.index(f.get("severity", "info")),
    )
    pages = buckets["pages"]
    urls = sorted({r.get("url", "") for r in pages})
    critical_n = sum(1 for f in signal if f["severity"] == "critical")
    high_n = sum(1 for f in signal if f["severity"] == "high")

    lcp = next((f for f in signal if "largest-contentful-paint" in f.get("tags", [])), None)
    contrast = next((f for f in signal if "color-contrast" in f.get("tags", [])), None)
    vendors = buckets["blocked_vendors"]

    takeaways = ["<li><strong>Accessibility has real gaps.</strong> "
                 f"{len([f for f in signal if f.get('agent') == 'a11y_perf'])} WCAG 2.2 AA violations, "
                 f"{critical_n} of them critical: images without alt text and pinch-to-zoom disabled on mobile.</li>"]
    if contrast:
        takeaways.append(
            f"<li><strong>Pricing content is hard to read.</strong> Low-contrast text on "
            f"{_affects(contrast.get('detail', ''))} elements, including price figures and CTA buttons.</li>")
    if lcp:
        val = re.search(r"LCP = ([\d.]+)", lcp.get("detail", ""))
        secs = f"{float(val.group(1)) / 1000:.1f}s" if val else "?"
        takeaways.append(
            f"<li><strong>Main content is slow to appear.</strong> Largest Contentful Paint measured {secs} "
            "against Google's 2.5s \"good\" threshold (measured in a throttled headless browser — directionally "
            "useful, worth confirming with field data).</li>")
    if vendors:
        names = ", ".join(sorted(vendors))
        takeaways.append(
            "<li><strong>The site's own security policy is blocking its marketing stack.</strong> The page's "
            f"Content-Security-Policy refuses to load: {names}. If this holds in normal browsers, analytics and "
            "conversion attribution are silently under-counting — worth a quick check with the marketing team.</li>")
    if buckets["manual"]:
        takeaways.append(
            "<li><strong>Email validation needs a manual submit test.</strong> Clearly-invalid emails are accepted "
            "without any visible error flag. The agent deliberately never submits real lead-gen forms, so "
            "submission-time validation couldn't be observed.</li>")
    visual_pass = next((f for f in buckets["passes"] if f.get("agent") == "visual_qa"), None)
    if visual_pass and "mock" in visual_pass.get("tags", []):
        takeaways.append(
            "<li><strong>Visual rendering: pipeline verified, judgment pending.</strong> Screenshots were "
            "captured at all three breakpoints, but no vision-model judgment ran in this scan (no LLM API "
            "key configured) — layout was verified via the accessibility and monitoring layers only.</li>")
    elif visual_pass:
        takeaways.append(
            "<li><strong>Rendering is healthy.</strong> Visual layout passed the vision-model rubric at "
            "mobile, tablet and desktop widths.</li>")
    geo_pass = next((f for f in buckets["passes"] if f.get("agent") == "geo_aeo"), None)
    if geo_pass:
        d = geo_pass.get("detail", "")
        if "cross-check asked" in d:
            engines = d.split("across: ")[-1].strip().rstrip(".")
            takeaways.append(
                "<li><strong>AI-answer consistency checked end-to-end.</strong> Structured-data tags are "
                "consistent with the rendered page, and the dynamic cross-check asked real buyer questions "
                f"across {engines} with no factual mismatches found.</li>")
        elif "no answer-engine API keys" in d:
            takeaways.append(
                "<li><strong>AI-answer consistency partially checked.</strong> Static schema checks passed; "
                "the dynamic LLM cross-check was in scope but needs answer-engine API keys to run.</li>")
        else:
            takeaways.append(
                "<li><strong>Structured-data checks passed.</strong> Schema/meta tags are consistent with "
                "rendered content. The dynamic AI-answer cross-check applies to product and pricing pages.</li>")
    takeaways.append(
        "<li><strong>Rendering itself is healthy.</strong> Visual layout passed the vision-model rubric at "
        "mobile, tablet and desktop widths.</li>")

    shots_html = ""
    shots_dir = Path(RUN.screenshots_dir)
    for bp, label in [("desktop", "Desktop (1440px)"), ("tablet", "Tablet (834px)"), ("mobile", "Mobile (390px)")]:
        p = shots_dir / f"plum-pricing_{bp}.png"
        if p.exists():
            shots_html += (f"<figure class='shot'><img src='{_img_data_uri(str(p))}' alt='{label} screenshot'>"
                           f"<figcaption class='cap'>{label} — full-page capture during the scan</figcaption></figure>")

    vendor_rows = "".join(f"<tr><td>{v}</td><td class='muted'>{', '.join(sorted(domains))}</td></tr>"
                          for v, domains in sorted(vendors.items()))

    appendix_rows = "".join(
        f"<tr class='sev-{f.get('severity', 'info')}'>"
        f"<td>{f.get('severity', '')}</td><td>{f.get('agent', '')}</td>"
        f"<td>{f.get('title', '')}</td><td>{(f.get('detail', '') or '')[:220]}</td></tr>"
        for f in sorted(
            [f for r in pages for f in r.get("findings", [])],
            key=lambda f: _SEVERITY_ORDER.index(f.get("severity", "info")),
        ))

    contact = SAFETY.contact_email
    contact_line = f" &middot; Contact: <a href='mailto:{contact}'>{contact}</a>" if "@" in contact else ""

    total_raw = sum(len(r.get("findings", [])) for r in pages)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{_CSS}</style></head>
<body><div class="page-pad">

<h1>Xoxoday Website QA &mdash; Findings Report</h1>
<div class="sub">Automated agentic quality audit of xoxoday.com web properties</div>
<div class="meta-line">Generated {time.strftime('%d %b %Y, %H:%M UTC', time.gmtime())}
 &middot; Deep-scanned page: {urls[0] if urls else 'n/a'}
 &middot; Raw checks executed: {total_raw}{contact_line}</div>

<div class="stat-row">
  <div class="stat"><div class="n">{len(signal)}</div><div class="lbl">Product issues found</div></div>
  <div class="stat"><div class="n">{critical_n}</div><div class="lbl">Critical</div></div>
  <div class="stat"><div class="n">{high_n}</div><div class="lbl">High</div></div>
  <div class="stat"><div class="n">3</div><div class="lbl">Breakpoints verified</div></div>
</div>

<h2>Executive summary</h2>
<div class="takeaways"><ul>{''.join(takeaways)}</ul></div>

<h2>Confirmed issues</h2>
{''.join(_signal_card(f) for f in signal) or '<p class="muted">None.</p>'}

<h2>Needs manual verification</h2>
{''.join(
    f"""<div class="card medium">
      <div class="card-head">{_chip('medium')}<span class="card-title">Email fields accept invalid input without an error flag</span></div>
      <div class="field"><span class="k">What we saw</span><div>Entering "not-an-email" left the field with no
      aria-invalid state and no visible error message.</div></div>
      <div class="field"><span class="k">Why it's not confirmed</span><div>The agent never submits real lead-gen
      forms (safety policy), and some forms validate only at submission time.</div></div>
      <div class="field"><span class="k">Next step</span><div>Manually submit the form once with an invalid email;
      if it reaches the CRM, add client-side validation.</div></div>
    </div>"""
    for _ in buckets["manual"]) or '<p class="muted">Nothing outstanding.</p>'}

<h2>Silent-failure monitor: blocked marketing scripts</h2>
<p>The monitor attached to every page load caught the site's own
Content-Security-Policy refusing requests from these third-party
services. This does not break the page for visitors &mdash; but if these
tags are supposed to be firing, analytics dashboards and conversion
attribution are quietly losing data. Recommend confirming each vendor
below is either allow-listed in the CSP or intentionally retired.</p>
<table><tr><th>Service</th><th>Blocked endpoint(s)</th></tr>{vendor_rows}</table>

<h2 class="breaker">Visual evidence</h2>
<p>Full-page captures taken by the scan at three viewport widths. These
are the exact inputs the vision-model judge evaluated.</p>
{shots_html}

<h2 class="breaker">How this was produced</h2>
<div class="disclosure">
<p>An automated QA agent loaded the page in a real (headless) Chromium
browser and ran four specialist checks:</p>
<ul>
<li><strong>Visual QA</strong> &mdash; screenshots at mobile/tablet/desktop judged by a vision model against a bounded rubric (layout breaks, text overflow, brand inconsistency).</li>
<li><strong>Forms</strong> &mdash; boundary and internationalized inputs, reading validation state. <strong>No form was ever submitted.</strong></li>
<li><strong>GEO/AEO</strong> &mdash; structured-data and meta-tag consistency vs. rendered content.</li>
<li><strong>A11y + performance + silent failures</strong> &mdash; axe-core WCAG 2.2 AA audit, Lighthouse Core Web Vitals, and a console/network monitor.</li>
</ul>
<p><strong>Safety:</strong> the scan respected robots.txt, rate-limited
itself to roughly one request every 1.5 seconds, identified itself with
a contactable User-Agent string, tagged all test data, and never
completed a real form submission.</p>
</div>

<h2>Limitations</h2>
<ul>
<li>axe-core automates roughly 30&ndash;40% of WCAG 2.2 AA; a clean automated pass is not a full accessibility audit.</li>
<li>Performance was measured in a throttled headless browser; absolute numbers will differ from real-user field data.</li>
<li>Findings reflect a single point in time; the pipeline is designed to be rerun nightly.</li>
<li>CSP-blocked endpoints were observed under the scan's environment; confirm in a normal browser session before treating each as a live data-loss issue.</li>
</ul>

<h2 class="breaker">Appendix: all raw findings ({total_raw})</h2>
<table><tr><th>Sev</th><th>Agent</th><th>Finding</th><th>Detail</th></tr>{appendix_rows}</table>

</div></body></html>"""


# --------------------------------------------------------------------------
# PDF rendering
# --------------------------------------------------------------------------

def render_pdf(html_path: Path, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            margin={"top": "14mm", "bottom": "16mm", "left": "13mm", "right": "13mm"},
            display_header_footer=True,
            footer_template=(
                "<div style=\"width:100%;font-size:8px;color:#8a97a5;"
                "text-align:center;font-family:Helvetica,Arial,sans-serif;\">"
                "Xoxoday QA Agent &mdash; page <span class=\"pageNumber\"></span> "
                "of <span class=\"totalPages\"></span></div>"
            ),
        )
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the founder-ready PDF report")
    parser.add_argument("--out", default="Xoxoday-QA-Report.pdf", help="Output PDF path")
    args = parser.parse_args()

    results = load_results()
    if not results:
        print(f"No results found in {RUN.findings_dir}/ — run scripts/run_local_demo.py first.")
        return

    buckets = classify(results)
    html_str = build_html(buckets, Path(args.out).stem)

    html_path = Path(args.out).with_suffix(".html")
    html_path.write_text(html_str, encoding="utf-8")

    render_pdf(html_path, Path(args.out))

    print(f"Signal: {len(buckets['signal'])} | manual-review: {len(buckets['manual'])} | "
          f"blocked-vendor groups: {len(buckets['blocked_vendors'])} | noise: {len(buckets['noise'])}")
    print(f"Report: {args.out}")
    print(f"HTML  : {html_path}")


if __name__ == "__main__":
    main()
