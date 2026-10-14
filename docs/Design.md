# Design — SiteSentinel

Two surfaces share one visual language: the **web app** (landing → progress → results) and the **A4 PDF report**.

## Direction — "Atelier" (v3)

A warm-ink atelier, not a blue tech gradient. The system is built around an ownable warm palette — near-black ink (`#0A0A08`) with bone/parchment text (`#F2EFE6`) and a single signal-vermillion accent (`#FF3A1A`, used only for action and live state). Severity colors are muted earth, not candy. Editorial typography does the heavy lifting: **Fraunces** display at `clamp(2.5rem, 8vw, 5.75rem)` with tight negative tracking, **Instrument Serif** italic for the accent phrase, **Inter** for body, **JetBrains Mono** micro-mono for every label and data point (uppercase, `.14em` tracking). A 2D canvas wireframe of a web page is swept by a warm scan plane behind the centered headline — draggable, parallax-reactive, and paused offscreen. The rest of the craft reads as a precision instrument crossed with an editorial art piece: film grain, 1px scroll-progress hairline, hairline rules, giant ghost section numerals, corner-tick brackets, pointer-tracked spotlight on capability cards, marquee divider, and magnetic hover on the primary CTA. No vendor badge ever, no lorem ipsum, no fake data.

## Tokens (`static/app.css`)

| Token | Value | Use |
|---|---|---|
| `--bg` / `--bg-2` / `--bg-3` | `#0A0A08` / `#11110F` / `#171713` | warm ink canvas, layered |
| `--surface` / `--surface-2` | `#1C1C18` / `#23231E` | panels, cards, inputs |
| `--text` / `--text-2` / `--text-3` | `#F2EFE6` / `#A8A39A` / `#6E6A62` | headings, body, labels & meta |
| `--border` / `--border-2` | `rgba(245,241,232,.07)` / `rgba(245,241,232,.12)` | warm hairline borders |
| `--accent` / `--grad` | `#FF3A1A` / `linear-gradient(112deg, #E84A18, #FF3A1A, #FF7A3D)` | action + live only |
| `--sev-critical` `--sev-high` `--sev-medium` `--sev-low` `--sev-ok` | `#C84A32` `#C07A2E` `#B89A2E` `#6B8FA0` `#5FA87A` | muted-earth severity |
| `--glass` / `--glass-2` | `rgba(245,241,232,.04)` / `rgba(245,241,232,.07)` | glass fills |

**Fraunces** (opsz-aware display) for headlines, **Instrument Serif** italic for the one accent phrase per headline, **Inter** for body, **JetBrains Mono** for machine-generated data — URLs, timestamps, metrics, IDs, code snippets. Border radii 6–16px; panels carry corner-tick brackets (`.ticks`) and capability cards a warm pointer-tracked radial spotlight (`.spot`).

## Layout

* 1160px measure, 58px sticky header (warm glass, hairline).
* Hero is full-viewport centered: status eyebrow, two-line Fraunces headline with a vermillion serif-italic accent, one sentence, the scan bar (magnetic CTA with beam sweep), one mono reassurance line, a four-cell warm spec strip (stages / viewports / standard / submits), and a subtle "drag to inspect" hint. Behind the headline a `<canvas>` renders a perspective wireframe of a web page being swept by a warm scan plane — draggable horizontally, parallax-reactive, paused offscreen, and replaced by a static poster under `prefers-reduced-motion`, no-WebGL, or touch-only.
* Seamless mono ticker below the hero — pauses on hover — never vendor names.
* Sections are separated by hairlines and air, each with a giant ghost numeral (`.ghost-num`) and a small uppercase vermillion label.
* "What it checks" is a five-card grid with per-check accent edge, icon chip and index — each card carries the warm mouse-tracked spotlight.
* "How it works" is three cards; a **marquee divider** (repeating SiteSentinel · Read-only · Deterministic · Evidence-backed) sits between Process and Safety.
* Safety is a 2×2 bordered grid of four claims.
* The report section pairs the real PDF cover (angled, with warm glow) with four short bullets.
* A warm bottom CTA closes the landing.

## Motion

Each effect encodes state or craft, and everything collapses under `prefers-reduced-motion`:

| Effect | Where | Why |
|---|---|---|
| Clip-path line reveal on headline | hero | editorial entrance, once |
| Staggered section reveals (IntersectionObserver) | landing | orientation, once |
| Canvas wireframe + vermillion scan plane (draggable, parallax) | hero | the "scanning a page" centerpiece — state of the instrument |
| 1px scroll-progress hairline (warm vermillion) | top edge | position at a glance |
| Smooth scroll (rAF lerp, fine-pointer only) | document | gallery-weight feel, gated |
| Custom cursor dot + lagging ring (expands on interactive) | document | craft, desktop fine-pointer only |
| Magnetic hover on primary CTA (+ beam sweep) | hero + results | tactility; sweep is affordance |
| Seamless mono ticker (pauses on hover) | landing | momentum |
| Pointer-tracked warm spotlight on capability cards | capabilities | tactility |
| Marquee divider | landing | rhythm between sections |
| Giant ghost numerals per section | landing | editorial hierarchy |
| SVG progress dial + glow beam | progress | exact pipeline completion |
| Blinking rail marker + accent edge on the running stage | progress | which stage is live |
| Live capture preview with scanline | progress | the target page, as it is captured |
| Colored telemetry terminal (ok/warn/err) | progress | severity at a glance |
| Rolling counters | progress + results | numbers land instead of appearing |
| Severity bar draw-in | results | the mix at a glance |
| Focus-managed lightbox | results gallery | keyboard operability |

## The hero centerpiece

A 2D `<canvas>` simulation — not Three.js — to stay well under the 200KB added-JS budget and keep the page dependency-free (no CDN runtime). A perspective-projected wireframe of a generic web page (nav, hero block, three cards, text lines, gallery, footer) is drawn with hairline strokes; a horizontal vermillion beam and soft glow sweep from top to bottom on a loop, briefly igniting any wireframe block it crosses. The whole page rig parallaxes with the pointer and can be dragged horizontally. IntersectionObserver pauses the rAF loop offscreen; `visibilitychange` pauses it when the tab is hidden. Under `prefers-reduced-motion`, WebGL-less, or touch-only environments the canvas is hidden and the hero degrades to a static poster (vignette + warm grid).

## States

Loading (hero → progress), empty ("No findings recorded for this target."), degraded (a stage marked with `▲` plus the engine's own reason in its detail line), error (a panel with the engine's message), offline (engine status chip reads "engine offline"). Each transition scrolls to the top of the new view. No-JS resilience: content is visible by default; every enhancement layer gates itself.

## Accessibility

Semantic landmarks, skip link, labelled input, `role="progressbar"` with live `aria-valuenow`, `aria-live="polite"` on the stage rail, real buttons and links, visible focus rings, and warm bone-on-ink at AA contrast everywhere. Gallery and lightbox are keyboard-operable with focus return. All WebGL / smooth-scroll / cursor layers are gated behind `(pointer: fine)` and `prefers-reduced-motion`.

## The PDF (`app/report.py`)

A4, rendered by Chromium's print pipeline from HTML + CSS.

1. **Cover** — dark, full bleed: brand line, headline, target URL, scan meta, four KPI cards, a "what was checked" block, and the safety rules footer.
2. **Executive summary + top risks** — model-written, two sentences, deterministic fallback.
3. **Core Web Vitals + stage table** — measured numbers, per-stage status and timing.
4. **Findings** — severity-ordered cards with a coloured rail, category, deterministic id, evidence block and a concrete fix.
5. **Evidence gallery** — embedded captures with viewport size and overflow verdict.
6. **Safety & compliance statement** — robots verdict, throttle, User-Agent, the three-layer no-submit policy with the recorded submission count, data handling, model policy.

Pillow generates the thumbnails that get embedded, keeping the PDF near 0.5 MB with three full-page captures inside it.
