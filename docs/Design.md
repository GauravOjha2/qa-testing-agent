# Design — visual system for the deliverable report

The product's only user-facing surface is the PDF/HTML report
(`scripts/generate_report.py`). Design goal: a non-engineer reads it
top-to-bottom; severity is legible at a glance; evidence is embedded, not linked.

## Color palette

| Token | Hex | Use |
|---|---|---|
| Ink | `#1c2733` | body text |
| Muted | `#5b6b7b` | secondary text, labels |
| Faint | `#7b8a99` | meta lines |
| Hairline | `#e2e9ef` | card/table borders |
| Panel bg | `#f4f7fa` | stat boxes, table headers |
| Takeaway bg | `#f8fafc` | exec-summary block |
| Accent | `#2563eb` | exec-summary left border (informational blue) |
| Critical | `#d32f2f` | chip + 5px card border |
| High | `#f57c00` | chip + card border |
| Medium | `#f0b400` | chip (dark text `#3a3000`) + card border |
| Low | `#9e9e9e` | chip + card border |

Severity color is carried by **two cues** (chip fill + left border), never by
color alone — the label text always names the severity.

## Typography

- Stack: `'Segoe UI', -apple-system, Helvetica, Arial, sans-serif`
- H1 26px / H2 17px / H3 14px / body 13px / tables+appendix 10.5px /
  chips & field labels 9.5–10.5px uppercase with letter-spacing
- Line-height 1.55; headings use negative tracking (-0.5px on H1)

## Layout rules

- A4 via Playwright `page.pdf()`, margins 14/16/13/13mm, footer with page
  numbers ("Xoxoday QA Agent — page N of M")
- Section order: header → stat row → executive summary → confirmed issues →
  manual verification → silent-failure monitor → *(page break)* visual evidence
  → *(page break)* methodology → limitations → *(page break)* appendix
- Stat row: 4 equal cards (issues found / critical / high / breakpoints)
- Finding cards: rounded 8px, 1px hairline border, 5px severity-colored left
  border, structured fields (`SCOPE`, `WHY IT MATTERS`, `RECOMMENDED FIX`,
  `HOW TO READ THIS`) as uppercase micro-labels
- Cards and figures use `page-break-inside: avoid`; section headings use
  `page-break-after: avoid`
- Screenshots: full-page captures centered, max-height 880px, aspect preserved,
  1px border + caption naming the viewport

## Voice

Plain English over jargon. Every issue answers three questions: what did we
see, why should the business care, what's the fix. Uncertainty is stated
("worth confirming", "needs manual test"), never hidden.
