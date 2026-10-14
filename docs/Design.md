# Design — SiteSentinel

Two surfaces share one visual language: the **web app** (landing, progress, results) and
the **A4 PDF report**.

## Direction

Precision diagnostic instrument — the "Instrument v2" system. Deep-space canvas
(`#050507`), editorial typography (**Space Grotesk** display × **Instrument Serif**
italic accents × **Inter** body × **JetBrains Mono** data), animated film grain, a soft
radar sweep behind the hero (the sentinel motif), hairline rules, corner-tick brackets
on instrument panels, mouse-tracked spotlight glow on capability cards, and a seamless
mono ticker of capability terms. Color is reserved for meaning: one signal-violet →
ice-cyan accent gradient for action, and the severity palette (`critical: #f0526a`,
`high: #fb923c`, `medium: #facc15`, `low: #60a5fa`, `ok: #34d399`) for findings. The interface balances high-density information architecture with precision typography and purposeful color: dark canvas (`#09090b`), high-contrast text hierarchy (`#e4e4e8`), hairline borders (`rgba(255,255,255,.08)`), and color reserved strictly for state and severity (`critical: #ef4444`, `high: #f97316`, `medium: #eab308`, `low: #3b82f6`, `ok: #22c55e`).

No generic AI SaaS templates, no lorem ipsum, and no decorative features that don't perform work. Implementation details are kept out of marketing copy. The landing page acts as an instrument console; during a scan, live SSE progress and screenshot captures stream directly into the live preview pane.

## Tokens (`static/app.css`)

| Token | Value | Use |
|---|---|---|
| `--bg` / `--bg-2` | `#050507` / `#0a0a0e` | deep-space canvas |
| `--surface` / `--surface-2` | `#0e0e13` / `#131319` | panels, cards, inputs |
| `--text` / `--text-2` / `--text-3` | `#eceef2` / `#9ba1ab` / `#63676f` | headings, body, labels & meta |
| `--border` / `--border-2` | `rgba(255,255,255,.08)` / `rgba(255,255,255,.12)` | precision hairline borders |
| `--accent` / `--grad` | `#8b8ff8` / `linear-gradient(120deg, #6366f1, #8b8ff8, #67e8f9)` | signal gradient, action only |
| `--sev-critical` `--sev-high` `--sev-medium` `--sev-low` `--sev-ok` | `#f0526a` `#fb923c` `#facc15` `#60a5fa` `#34d399` | severity, shared across web & PDF |

**Space Grotesk** for display and headings, **Instrument Serif** italic for one accent phrase per headline, **Inter** for body, **JetBrains Mono** for machine-generated data — URLs, timestamps, metrics, IDs, code snippets. Border radii 6–16px; panels carry corner-tick brackets (`.ticks`) and capability cards a pointer-tracked radial spotlight (`.spot`).


The palette is not invented. It is the pattern that holds across the reference set used to
design this: near-monochrome surfaces, one accent, mono for data (shadcn, Refero, Component
Gallery, mapcn, Minimal Gallery all sit in the same neutral range).

## Layout

* 1080px measure, 60px sticky header with a single hairline.
* Hero is centered: status eyebrow, a two-line display headline with a serif-italic gradient
  accent, one sentence, the scan bar (beam-sweep primary button), one mono reassurance line,
  and a four-cell spec strip (stages / viewports / standard / submits). A blurred radar sweep
  rotates behind the headline. Below the hero, a seamless mono ticker lists capabilities —
  never vendor names.
* Sections are separated by 104px of space and a hairline, each with a small uppercase
  label rather than a decorated heading.
* "What it checks" is a five-card grid with per-check accent edge, icon chip and index — each
  card carries the mouse-tracked spotlight.
* Safety is a 2×2 bordered grid of four one-line claims.
* The report section pairs the real PDF cover with four short bullets.

## Motion

Each effect communicates state or craft, and everything collapses under
`prefers-reduced-motion`:

| Effect | Where | Why |
|---|---|---|
| Staggered hero reveal | landing | orientation, once |
| Radar sweep | hero | the sentinel motif — slow, blurred, ambient |
| Seamless capability ticker | landing | momentum; pauses on hover |
| Pointer-tracked spotlight | capability cards | tactility (fine pointers only) |
| Beam sweep on primary button | landing + results | affordance |
| SVG progress dial + glow beam | progress | exact pipeline completion |
| Blinking rail marker + accent edge on the running stage | progress | which stage is live |
| Live capture preview with scanline | progress | the target page, as it is captured |
| Colored telemetry terminal | progress | ok / warn / error at a glance |
| Rolling counters | progress + results | numbers land instead of appearing |
| Severity beam draw-in | results | the mix at a glance |
| Section reveal on scroll | landing | orientation, once, subtle |

## States## States

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


