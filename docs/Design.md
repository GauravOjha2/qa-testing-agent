# Design — visual system for the deliverable report

The product's only user-facing surface is the PDF report
(`adk_qa_pipeline/generate_pdf.py`). Design goal: a non-engineer reads it
top-to-bottom; severity is legible at a glance; evidence is embedded, not linked.

## Color palette

| Token | Hex | Use |
|---|---|---|
| Cover bg | `#111827` | header band |
| Cover text | `#f9fafb` / `#9ca3af` | title / meta lines |
| Ink | `#1f2937` | body text |
| Detail | `#374151` | finding detail paragraphs |
| Muted | `#6b7280` | tool labels, captions |
| Faint | `#9ca3af` | tags line |
| Hairline | `#e5e7eb` | card/table/figure borders |
| Panel bg | `#f3f4f6` | appendix `<pre>` block |
| Safety bg | `#f0fdf4` + `#bbf7d0` border + `#166534` text | compliance footer |
| Critical | `#dc2626` | chip fill, left border, KPI number |
| High | `#ea580c` | chip + left border, KPI number |
| Medium | `#d97706` | chip + left border, KPI number |
| Low | `#64748b` | chip + left border |
| Info | `#0f766e` | chip + left border |

Severity is carried by **two cues** (chip fill + 4px left border) plus the label
text itself — never by color alone.

## Typography

- Stack: `'Segoe UI', Arial, sans-serif`
- Cover H1 21pt; H2 13pt with 2px `#111827` underline; body 10.5pt / 1.45
- Chips 7pt bold, letter-spacing `.04em`; finding titles 10pt semibold;
  details 9pt; tags/captions/tool labels 7.5–8pt; appendix 7.5pt monospace

## Layout

- A4 via Playwright `page.pdf()`; margins 16/16/13/13mm; `print_background: true`
- Section order: dark cover card (target, timestamp, pipeline, elapsed) →
  KPI row (total / critical / high / medium / tool-runs-ok, colored numbers) →
  top risks list → evidence captures → all findings → appendix
  (supervisor aggregate, truncated) → green safety-compliance box
- Finding cards: 1px hairline border, 4px severity left border, 6px radius;
  header row = severity chip · title · italic source-tool name;
  `page-break-inside: avoid`
- Screenshots are **pre-sliced**: width-normalized to 900px, chopped into
  aspect-1.45 JPEG chunks (q82) so no `<img>` spans multiple printed pages —
  Chromium's print tiler otherwise renders multi-page-tall images as black
  bands. Captions read "automated capture (part N/M)" — honest about provenance.
- Output: `ADK-QA-Report_<slug>.pdf` at repo root, slug derived from the
  target URL (filename-agnostic, works for any audited domain).

## Voice

Plain English over jargon. Every issue answers three questions: what did we
see, why should the business care, what's the fix. Uncertainty is stated
("needs manual confirmation"), never hidden. The safety footer states exactly
what was and wasn't done to the site.
