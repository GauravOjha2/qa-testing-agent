# Design — SiteSentinel

Two surfaces share one visual language: the **web app** (landing, progress, results) and
the **A4 PDF report**.

## Direction

Dark engineering-lab diagnostic instrument. The interface balances high-density information architecture with precision typography and purposeful color: dark canvas (`#09090b`), high-contrast text hierarchy (`#e4e4e8`), hairline borders (`rgba(255,255,255,.08)`), and color reserved strictly for state and severity (`critical: #ef4444`, `high: #f97316`, `medium: #eab308`, `low: #3b82f6`, `ok: #22c55e`).

No generic AI SaaS templates, no lorem ipsum, and no decorative features that don't perform work. Implementation details are kept out of marketing copy. The landing page acts as an instrument console; during a scan, live SSE progress and screenshot captures stream directly into the live preview pane.

## Tokens (`static/app.css`)

| Token | Value | Use |
|---|---|---|
| `--bg` / `--bg-2` | `#09090b` / `#0f0f13` | deep canvas background |
| `--surface` / `--surface-2` | `#141418` / `#1a1a20` | panels, cards, inputs |
| `--text` / `--text-2` / `--text-3` | `#e4e4e8` / `#a1a1aa` / `#71717a` | headings, body, labels & meta |
| `--border` / `--border-2` | `rgba(255,255,255,.08)` / `rgba(255,255,255,.12)` | precision hairline borders |
| `--accent` / `--grad` | `#818cf8` / `linear-gradient(135deg, #6366f1, #818cf8, #22d3ee)` | primary brand gradient |
| `--sev-critical` `--sev-high` `--sev-medium` `--sev-low` `--sev-ok` | `#ef4444` `#f97316` `#eab308` `#3b82f6` `#22c55e` | severity, shared across web & PDF |

**Inter** for all structural typography; **JetBrains Mono** for machine-generated data — URLs, timestamps, metrics, IDs, code snippets. Border radii are restrained (6–14px) to retain an engineering instrument aesthetic.


The palette is not invented. It is the pattern that holds across the reference set used to
design this: near-monochrome surfaces, one accent, mono for data (shadcn, Refero, Component
Gallery, mapcn, Minimal Gallery all sit in the same neutral range).

## Layout

* 1080px measure, 60px sticky header with a single hairline.
* Hero is left-aligned, max 760px, one headline, one sentence, one input row, one line of
  plain reassurance. No badge, no chip row, no scroll cue.
* Sections are separated by 104px of space and a hairline, each with a small uppercase
  label rather than a decorated heading.
* "What it checks" is a five-row definition list (index · name · description) — a table is
  the honest shape for a list of checks.
* Safety is a 2×2 bordered grid of four one-line claims.
* The report section pairs the real PDF cover with four short bullets.

## Motion

Kept, because each one communicates state or craft:

| Effect | Where | Why |
|---|---|---|
| Hover lift on the primary button | all views | affordance |
| Progress fill + blinking rail marker | progress | which stage is running |
| Live capture preview with a slow sweep line | progress | the target page, as it is captured |
| Rolling counters | progress + results | numbers land instead of appearing |
| Section reveal on scroll | landing | orientation, once, subtle |
| Staggered finding entrance | results | shows the list is fresh |

Everything above collapses under `prefers-reduced-motion`.

## States

Loading (hero → progress), empty ("Nothing in this run met a reporting threshold"), degraded
(a stage marked `~` with the engine's own reason in its detail line), error (a panel with the
engine's message), success (results). Each transition scrolls to the top of the new view.

## Accessibility of the UI

Semantic landmarks, skip link, labelled input, `role="progressbar"` with live `aria-valuenow`,
`aria-live="polite"` on the stage list, real buttons and links, visible focus rings, and ink on
paper at AA contrast everywhere.

## The PDF (`app/report.py`)

A4, rendered by Chromium's print pipeline from HTML + CSS.

1. **Cover** — dark, full bleed: brand line, headline, target URL, scan meta, four KPI cards,
   a "what was checked" block, and the safety rules footer.
2. **Executive summary + top risks** — model-written, two sentences, deterministic fallback.
3. **Core Web Vitals + stage table** — measured numbers, per-stage status and timing.
4. **Findings** — severity-ordered cards with a coloured rail, category, deterministic id,
   evidence block and a concrete fix.
5. **Evidence gallery** — embedded captures with viewport size and overflow verdict.
6. **Safety & compliance statement** — robots verdict, throttle, User-Agent, the three-layer
   no-submit policy with the recorded submission count, data handling, model policy.

Pillow generates the thumbnails that get embedded, keeping the PDF near 0.5 MB with three
full-page captures inside it. The report stays dark on purpose: it is a document, and it is
the one surface where a coloured cover carries meaning.
