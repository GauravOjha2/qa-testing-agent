# Design — SiteSentinel

Two surfaces share one visual language: the **web app** (landing, progress, results) and
the **A4 PDF report**.

## Direction

Paper and ink. The page should read like a document written by someone who knows the
subject — not a landing page performing enthusiasm. That means: one neutral background,
near-black type, hairline rules instead of boxes and shadows, generous space, and colour
reserved almost entirely for severity.

Concretely, the following were deliberately removed after the first pass, because they
were noise rather than design: the aurora/orb/meteor backdrop, the hero particle canvas,
gradient-filled headline text, gradient buttons, a tool marquee, a "stack" grid, orbiting
dots, border beams, magnetic buttons, 3D card tilt, a serif italic accent, and every badge
naming an implementation detail (`Playwright`, `axe-core`, `gemini-flash-latest`). None of
that told the user anything; all of it competed with the content.

## Tokens (`static/app.css`)

| Token | Value | Use |
|---|---|---|
| `--paper` | `#fafaf9` | page background |
| `--card` | `#ffffff` | panels, inputs, gallery frames |
| `--ink` | `#0f0f0e` | headings, primary buttons, progress fill |
| `--ink-2` | `#57534e` | body copy |
| `--ink-3` | `#8a8781` | labels, meta, mono captions |
| `--line` / `--line-2` | `#e7e5e4` / `#d6d3d1` | hairlines, input borders |
| `--accent` | `#2563eb` | focus ring, running state only |
| `--crit` `--high` `--med` `--low` `--ok` | `#d92d20` `#c2410c` `#a16207` `#175cd3` `#087443` | severity, shared with the PDF |

**Inter** for everything structural; **JetBrains Mono** for values the machine produced —
URLs, durations, metric numbers, finding ids, stage status. Radii stay small (8–12px):
pills read consumer, and this is a tool.

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
