/* ============================================================================
   SiteSentinel — Frontend controller v2 ("Instrument")
   Landing → live console (SSE) → QA workspace. Zero dependencies, ES2022.
   Interactions: scroll reveal, mouse spotlight, seamless ticker, SVG progress
   dial, count-ups, colored telemetry, focus-managed lightbox, health status.
   ========================================================================== */

(() => {
  "use strict";

  const API = (window.SENTINEL_API || "").replace(/\/$/, "");
  const url_ = (path) => `${API}${path}`;
  const $ = (id) => document.getElementById(id);

  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  };

  const esc = (v) => String(v === null || v === undefined ? "" : v);

  const svg = (paths, size = 18, viewBox = "0 0 24 24") =>
    `<svg viewBox="${viewBox}" width="${size}" height="${size}" aria-hidden="true">${paths}</svg>`;

  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)");

  /* ─── Static data ─────────────────────────────────────────────────────── */
  const ICONS = {
    layout: '<rect x="3" y="4" width="18" height="13" rx="2.2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 20h8M12 17v3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M3 8.5h18" fill="none" stroke="currentColor" stroke-width="1.6"/>',
    a11y: '<circle cx="12" cy="4.6" r="2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M4.5 8.6c2.4.9 4.9 1.3 7.5 1.3s5.1-.4 7.5-1.3M12 9.9v4.3m0 0-3 6m3-6 3 6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    speed: '<path d="M4 18a8 8 0 1 1 16 0" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="m12 18 4.2-5.6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="12" cy="18" r="1.5" fill="currentColor"/>',
    forms: '<rect x="3" y="5" width="18" height="14" rx="2.2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M7 10h6M7 14h3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="m15 14 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    answer: '<path d="M4.5 6.5A2.5 2.5 0 0 1 7 4h10a2.5 2.5 0 0 1 2.5 2.5v6A2.5 2.5 0 0 1 17 15H9l-4.5 4v-12.5Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M8.5 9.5h7M8.5 12h4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    check: '<path d="m5 12.5 4.4 4.4L19 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  };

  const CHECKS = [
    { num: "01", title: "Responsive Viewports",
      desc: "Full-page captures at mobile (390px), tablet (768px), and desktop (1440px), plus horizontal-overflow fault detection.",
      icon: "layout", color: "#8b8ff8", tint: "rgba(139,143,248,.10)", edge: "rgba(139,143,248,.24)" },
    { num: "02", title: "Accessibility Audit",
      desc: "Automated engine enforcing WCAG 2.2 A/AA criteria with precise DOM selector and code snippet evidence.",
      icon: "a11y", color: "#67e8f9", tint: "rgba(103,232,249,.08)", edge: "rgba(103,232,249,.2)" },
    { num: "03", title: "Core Web Vitals",
      desc: "Mobile performance evaluation measuring LCP, CLS, and TBT/INP against production ranking thresholds.",
      icon: "speed", color: "#facc15", tint: "rgba(250,204,21,.08)", edge: "rgba(250,204,21,.2)" },
    { num: "04", title: "Form Safety & Boundaries",
      desc: "Every input field tested with boundary, invalid, and international characters. Triply guarded against submission.",
      icon: "forms", color: "#f0526a", tint: "rgba(240,82,106,.08)", edge: "rgba(240,82,106,.22)" },
    { num: "05", title: "AI Answer Readiness",
      desc: "Multimodal AI evaluation checking whether generative answer engines can accurately cite product claims.",
      icon: "answer", color: "#34d399", tint: "rgba(52,211,153,.08)", edge: "rgba(52,211,153,.22)" },
  ];

  const STEPS = [
    { num: "01", title: "Target verification",
      desc: "Submit a public URL. The scanner first inspects robots.txt under a strict fail-closed policy before accessing the page." },
    { num: "02", title: "Headless pipeline",
      desc: "Five specialized stages execute in sequence, streaming live telemetry and screenshot previews over SSE." },
    { num: "03", title: "Synthesis & delivery",
      desc: "Deduplicated findings, Core Web Vitals grades, and an executive summary compile into structured JSON and an A4 PDF." },
  ];

  const FACTS = [
    { title: "Fail-closed robots.txt",
      desc: "robots.txt is verified before any page access. If denied or unreachable, the scan terminates immediately." },
    { title: "Zero-submit guarantee",
      desc: "submit/requestSubmit are stubbed, a capture-phase listener cancels submit events, and the network layer aborts non-GET requests." },
    { title: "Single-page isolation",
      desc: "Only the exact URL provided is inspected. The engine never crawls or traverses outbound links." },
    { title: "2-hour ephemeral storage",
      desc: "All screenshots, reports, and job records are purged automatically via TTL sweeps after two hours." },
  ];

  const STAGE_ORDER = [
    ["screenshots", "Captures", "Viewport captures"],
    ["accessibility", "Accessibility", "WCAG 2.2 audit"],
    ["vitals", "Performance", "Core Web Vitals"],
    ["forms", "Forms", "Validation probing"],
    ["ai", "AI Intel", "GEO/AEO analysis"],
  ];
  const STAGE_LABELS = Object.fromEntries(STAGE_ORDER.map((r) => [r[0], r[1]]));

  const SEV_COLOR = {
    critical: "#f0526a",
    high: "#fb923c",
    medium: "#facc15",
    low: "#60a5fa",
    info: "#7b7f88",
  };

  /* ─── Ambient interactions ────────────────────────────────────────────── */
  function initReveal() {
    const nodes = document.querySelectorAll("[data-reveal]");
    if (REDUCED.matches || !("IntersectionObserver" in window)) {
      nodes.forEach((n) => n.classList.add("in"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -6% 0px" }
    );
    nodes.forEach((n, i) => {
      if (n.closest(".hero")) n.style.setProperty("--d", `${Math.min(i * 90, 450)}ms`);
      io.observe(n);
    });
  }

  function initSpotlight() {
    if (REDUCED.matches || !window.matchMedia("(pointer: fine)").matches) return;
    document.addEventListener("pointermove", (e) => {
      const card = e.target.closest && e.target.closest(".spot");
      if (!card) return;
      const rect = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${e.clientX - rect.left}px`);
      card.style.setProperty("--my", `${e.clientY - rect.top}px`);
    }, { passive: true });
  }

  function initTicker() {
    const inner = $("tickerInner");
    if (!inner) return;
    // Duplicate content for a seamless -50% loop.
    const clone = inner.innerHTML;
    const dup = document.createElement("div");
    dup.setAttribute("aria-hidden", "true");
    dup.style.display = "contents";
    dup.innerHTML = clone;
    inner.append(...dup.childNodes);
  }

  /* ─── Landing content ─────────────────────────────────────────────────── */
  function renderChecks() {
    const host = $("checkList");
    if (!host) return;
    host.innerHTML = "";
    CHECKS.forEach((c, i) => {
      const card = el("article", "cap-card spot");
      card.style.setProperty("--cap-color", c.color);
      card.style.setProperty("--cap-tint", c.tint);
      card.style.setProperty("--cap-edge", c.edge);
      card.setAttribute("data-reveal", "");
      card.style.setProperty("--d", `${(i % 3) * 80}ms`);
      card.innerHTML = `
        <span class="cap-num mono">${c.num}</span>
        <div class="cap-icon">${svg(ICONS[c.icon], 19)}</div>
        <h3>${esc(c.title)}</h3>
        <p>${esc(c.desc)}</p>
      `;
      host.append(card);
    });
  }

  function renderSteps() {
    const host = $("stepList");
    if (!host) return;
    host.innerHTML = "";
    STEPS.forEach((s, i) => {
      const card = el("div", "flow-card");
      card.setAttribute("data-reveal", "");
      card.style.setProperty("--d", `${i * 100}ms`);
      card.innerHTML = `
        <span class="flow-num mono">${s.num}</span>
        <h3>${esc(s.title)}</h3>
        <p>${esc(s.desc)}</p>
      `;
      host.append(card);
    });
  }

  function renderFacts() {
    const host = $("factList");
    if (!host) return;
    host.innerHTML = "";
    FACTS.forEach((f, i) => {
      const item = el("div", "safety-item");
      item.setAttribute("data-reveal", "");
      item.style.setProperty("--d", `${(i % 2) * 90}ms`);
      item.innerHTML = `
        <span class="safety-check">${svg(ICONS.check, 12)}</span>
        <dl>
          <dt>${esc(f.title)}</dt>
          <dd>${esc(f.desc)}</dd>
        </dl>
      `;
      host.append(item);
    });
  }

  /* ─── View routing ────────────────────────────────────────────────────── */
  function show(viewName) {
    ["landing", "progress", "results", "error"].forEach((name) => {
      const node = $("view-" + name);
      if (!node) return;
      const isActive = name === viewName;
      node.classList.toggle("is-active", isActive);
      node.hidden = !isActive;
    });
    window.scrollTo({ top: 0, behavior: REDUCED.matches ? "auto" : "smooth" });
  }

  /* ─── Engine health → nav status ──────────────────────────────────────── */
  async function checkHealth() {
    const status = $("navStatus");
    try {
      const res = await fetch(url_("/api/health"));
      if (!res.ok) throw new Error("unhealthy");
      const data = await res.json();
      if (status) {
        status.classList.add("ok");
        const text = status.querySelector(".status-text");
        if (text) text.textContent = "engine online";
      }
      if (!data.ai_enabled) {
        const help = $("urlHelp");
        if (help) {
          help.textContent = "Read-only scan · robots.txt fail-closed · forms never submitted (AI layer disabled on this instance)";
        }
      }
    } catch {
      if (status) {
        status.classList.add("down");
        const text = status.querySelector(".status-text");
        if (text) text.textContent = "engine offline";
      }
    }
  }

  /* ─── Dial + progress beam ────────────────────────────────────────────── */
  const DIAL_C = 326.7256;

  function setProgress(pct) {
    const clamped = Math.max(0, Math.min(100, pct));
    const dialFill = $("dialFill");
    if (dialFill) dialFill.style.strokeDashoffset = String(DIAL_C * (1 - clamped / 100));
    const dialPct = $("dialPct");
    if (dialPct) dialPct.textContent = String(Math.round(clamped));
    const dial = $("dial");
    if (dial) dial.setAttribute("aria-valuenow", String(Math.round(clamped)));
    const barFill = $("barFill");
    if (barFill) barFill.style.width = `${clamped}%`;
    const barGlow = $("barGlow");
    if (barGlow) barGlow.style.width = `${clamped}%`;
  }

  /* ─── Progress management ─────────────────────────────────────────────── */
  function renderRail() {
    const rail = $("stageList");
    if (!rail) return;
    rail.innerHTML = "";
    STAGE_ORDER.forEach(([key, title, subtitle]) => {
      const row = el("div", "stage-item");
      row.dataset.key = key;
      row.dataset.status = "pending";
      row.innerHTML = `
        <span class="stage-mark mono">○</span>
        <div class="stage-info">
          <span class="stage-name">${esc(title)}</span>
          <span class="stage-detail mono">${esc(subtitle)} · queued</span>
        </div>
        <span class="stage-time mono">—</span>
      `;
      rail.append(row);
    });
  }

  let liveIssues = 0;

  function updateStage(event) {
    const row = document.querySelector(`.stage-item[data-key="${event.key}"]`);
    if (!row) return;

    row.dataset.status = event.status || "ok";
    const mark = row.querySelector(".stage-mark");
    if (mark) {
      mark.textContent =
        event.status === "ok" ? "✓" :
        event.status === "failed" ? "✗" :
        event.status === "degraded" ? "▲" : "●";
    }

    const detail = row.querySelector(".stage-detail");
    if (detail) {
      detail.textContent = event.detail || (event.status === "running" ? "in progress…" : detail.textContent);
    }

    const time = row.querySelector(".stage-time");
    if (time && typeof event.elapsed_seconds === "number") {
      time.textContent = `${event.elapsed_seconds}s`;
    }

    const settled = document.querySelectorAll(
      '.stage-item[data-status="ok"], .stage-item[data-status="failed"], .stage-item[data-status="degraded"]'
    ).length;
    setProgress(Math.min(99, Math.round((settled / STAGE_ORDER.length) * 100)));

    const liveStages = $("liveStages");
    if (liveStages) liveStages.textContent = `${settled} / ${STAGE_ORDER.length}`;

    const label = STAGE_LABELS[event.key] || event.label;
    const liveActivity = $("liveActivity");
    if (liveActivity) {
      liveActivity.textContent = event.status === "running" ? label : `${label} · ${event.status}`;
    }

    if (event.key === "screenshots" && event.status !== "running" && event.status !== "failed") {
      loadPreview(event.viewports);
    }

    if (typeof event.findings_total === "number" && event.findings_total !== liveIssues) {
      liveIssues = event.findings_total;
      countUp($("liveFindings"), liveIssues, 350);
    }
  }

  function logLine(message) {
    const box = $("console");
    if (!box) return;
    const ts = new Date().toLocaleTimeString([], { hour12: false });
    const tsNode = el("span", "log-ts", `[${ts}] `);
    const msgNode = el("span", "log-msg", message);
    const tone = /✗|fail|error|refus|denied/i.test(message) ? "err"
      : /degrad|warn|fallback/i.test(message) ? "warn"
      : /✓|\bok\b|complete|verified|captured/i.test(message) ? "ok" : "";
    if (tone) msgNode.classList.add(tone);
    box.append(tsNode, msgNode, document.createTextNode("\n"));
    box.scrollTop = box.scrollHeight;
  }

  let activeScanId = null;
  let previewLoaded = false;

  function resetPreview() {
    const frame = $("previewFrame");
    if (frame) frame.classList.remove("ready");
    const img = $("previewImg");
    if (img) {
      img.hidden = true;
      img.removeAttribute("src");
    }
    const empty = $("previewEmpty");
    if (empty) {
      const s = empty.querySelector("span");
      if (s) s.textContent = "Awaiting first capture";
    }
    const badge = $("previewBadge");
    if (badge) badge.lastChild.textContent = "queued";
    const meta = $("previewMeta");
    if (meta) meta.textContent = "desktop · 1440px";
    previewLoaded = false;
  }

  function loadPreview(viewports) {
    if (previewLoaded || !activeScanId) return;
    previewLoaded = true;
    const probe = new Image();
    probe.onload = () => {
      const target = $("previewImg");
      if (target) {
        target.src = probe.src;
        target.hidden = false;
      }
      const frame = $("previewFrame");
      if (frame) frame.classList.add("ready");
      const badge = $("previewBadge");
      if (badge) badge.lastChild.textContent = "captured";
      const meta = $("previewMeta");
      if (meta) {
        const count = viewports && viewports.length ? viewports.length : 1;
        meta.textContent = `live capture · ${count} viewports`;
      }
    };
    probe.onerror = () => {
      previewLoaded = false;
      const empty = $("previewEmpty");
      if (empty) {
        const s = empty.querySelector("span");
        if (s) s.textContent = "Preview unavailable";
      }
    };
    probe.src = url_(`/api/scan/${activeScanId}/shot/desktop.jpg?t=${Date.now()}`);
  }

  let timer = null;
  function startTimer() {
    const t0 = Date.now();
    clearInterval(timer);
    timer = setInterval(() => {
      const s = Math.floor((Date.now() - t0) / 1000);
      const m = String(Math.floor(s / 60)).padStart(2, "0");
      const sec = String(s % 60).padStart(2, "0");
      const elap = $("elapsed");
      if (elap) elap.textContent = `${m}:${sec}`;
    }, 1000);
  }

  /* ─── Animated counter ────────────────────────────────────────────────── */
  function countUp(node, value, duration = 600) {
    if (!node) return;
    if (REDUCED.matches) {
      node.textContent = String(value);
      return;
    }
    const start = performance.now();
    const tick = (now) => {
      const progress = Math.min(1, (now - start) / duration);
      const ease = 1 - Math.pow(1 - progress, 3);
      node.textContent = String(Math.round(value * ease));
      if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  /* ─── Results rendering ───────────────────────────────────────────────── */
  function renderKPI(count, label, severityClass) {
    const card = el("div", `kpi ${severityClass}`);
    const val = el("div", "kpi-value", "0");
    const lbl = el("div", "kpi-label", label);
    card.append(val, lbl);
    countUp(val, count);
    return card;
  }

  function renderMix(counts) {
    const host = $("mix");
    if (!host) return;
    host.innerHTML = "";
    const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;

    host.append(el("div", "mix-title mono", "Severity distribution"));

    const bar = el("div", "mix-bar");
    const legend = el("div", "mix-legend mono");

    ["critical", "high", "medium", "low", "info"].forEach((sev) => {
      const value = counts[sev] || 0;
      if (!value) return;
      const seg = el("span");
      seg.style.width = `${(value / total) * 100}%`;
      seg.style.background = SEV_COLOR[sev];
      seg.style.color = SEV_COLOR[sev];
      bar.append(seg);

      const item = el("span");
      const dot = el("i");
      dot.style.background = SEV_COLOR[sev];
      dot.style.color = SEV_COLOR[sev];
      item.append(dot, document.createTextNode(`${sev} · ${value}`));
      legend.append(item);
    });

    host.append(bar, legend);
  }

  function renderVitalCard(label, value, unit, thresholds, decimals) {
    const card = el("div", "vital-item");
    if (value === null || value === undefined) {
      card.append(el("div", "vital-value", "n/a"));
    } else {
      const shown = decimals !== undefined
        ? Number(value).toFixed(decimals)
        : unit === ""
        ? Number(value).toFixed(2)
        : `${Math.round(value)}${unit}`;
      card.append(el("div", "vital-value", shown));
      if (thresholds) {
        card.classList.add(value > thresholds[1] ? "bad" : value > thresholds[0] ? "warn" : "good");
      }
    }
    card.append(el("div", "vital-label mono", label));
    return card;
  }

  function renderVitals(vitals) {
    const host = $("vitals");
    if (!host) return;
    host.innerHTML = "";
    if (!vitals || !vitals.source) {
      host.append(el("p", "vitals-note", "Core Web Vitals were not captured for this scan."));
      return;
    }

    host.append(renderVitalCard("LCP", vitals.lcp_ms, "ms", [2500, 4000]));
    host.append(renderVitalCard("CLS", vitals.cls, "", [0.1, 0.25]));
    host.append(renderVitalCard("INP", vitals.inp_ms, "ms", [200, 500]));
    host.append(renderVitalCard("TBT", vitals.tbt_ms, "ms", [200, 600]));

    if (vitals.performance_score !== null && vitals.performance_score !== undefined) {
      host.append(renderVitalCard("Score", vitals.performance_score, "", null, 0));
    }

    const note = el("p", "vitals-note mono");
    note.textContent = `Source: ${vitals.source}.${vitals.inp_note ? " " + vitals.inp_note : ""}`;
    host.append(note);
  }

  function renderGallery(shots, scanId) {
    const host = $("gallery");
    if (!host) return;
    host.innerHTML = "";
    if (!shots || !shots.length) {
      host.append(el("p", "vitals-note", "No captures recorded."));
      return;
    }

    shots.forEach((shot) => {
      const fig = el("figure", "shot");
      fig.tabIndex = 0;
      fig.setAttribute("role", "button");
      fig.setAttribute("aria-label", `Open ${shot.viewport} capture full size`);
      const img = el("img");
      img.src = url_(`/api/scan/${scanId}/shot/${shot.viewport}.jpg`);
      img.alt = `${shot.viewport} viewport capture (${shot.width}x${shot.height})`;
      img.loading = "lazy";

      const open = () =>
        openLightbox(url_(`/api/scan/${scanId}/shot/${shot.viewport}.png`), img.alt, fig);
      fig.addEventListener("click", open);
      fig.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      });

      const cap = el("figcaption");
      cap.append(el("span", null, `${shot.viewport} · ${shot.width}×${shot.height}`));
      const chip = el(
        "span",
        `chip ${shot.overflow_x ? "warn" : "ok"}`,
        shot.overflow_x ? `+${shot.overflow_px}px overflow` : "fits"
      );
      cap.append(chip);
      fig.append(img, cap);
      host.append(fig);
    });
  }

  /* ─── Lightbox (focus-managed) ────────────────────────────────────────── */
  let lightboxTrigger = null;

  function openLightbox(src, alt, trigger) {
    const lb = $("lightbox");
    const img = $("lightboxImg");
    if (!lb || !img) return;
    lightboxTrigger = trigger || null;
    img.src = src;
    img.alt = alt || "";
    lb.hidden = false;
    document.body.style.overflow = "hidden";
    const closeBtn = lb.querySelector(".lightbox-close");
    if (closeBtn) closeBtn.focus();
  }

  function closeLightbox() {
    const lb = $("lightbox");
    if (!lb || lb.hidden) return;
    lb.hidden = true;
    document.body.style.overflow = "";
    if (lightboxTrigger && document.contains(lightboxTrigger)) {
      lightboxTrigger.focus();
    }
    lightboxTrigger = null;
  }

  /* ─── Findings ────────────────────────────────────────────────────────── */
  let currentResult = null;
  let activeFilter = "all";

  function createEvidenceBox(ev) {
    const box = el("div", "ev-box");
    Object.entries(ev || {}).forEach(([key, val]) => {
      const str = String(val === null || val === undefined ? "" : val).trim();
      if (!str) return;
      const row = el("div");
      row.append(el("b", null, key));
      row.append(el("span", null, str.length > 360 ? str.slice(0, 360) + "…" : str));
      box.append(row);
    });
    return box;
  }

  function createFindingElement(f) {
    const item = el("details", `finding ${f.severity}`);
    const summary = el("summary");
    summary.append(el("span", "sev mono", f.severity.toUpperCase()));
    summary.append(el("span", "f-title", f.title));
    summary.append(el("span", "f-meta mono", `${f.category} · ${f.id}`));
    item.append(summary);

    const body = el("div", "f-body");
    if (f.detail) {
      body.append(el("p", null, f.detail));
    }
    if (f.evidence && Object.keys(f.evidence).length) {
      body.append(createEvidenceBox(f.evidence));
    }
    if (f.recommendation) {
      const rec = el("p", "f-rec");
      rec.append(el("strong", null, "Fix — "));
      rec.append(document.createTextNode(f.recommendation));
      body.append(rec);
    }
    item.append(body);
    return item;
  }

  function renderFindings() {
    const host = $("findings");
    if (!host) return;
    host.innerHTML = "";

    const list = ((currentResult && currentResult.findings) || []).filter(
      (f) => activeFilter === "all" || f.severity === activeFilter
    );

    if (!list.length) {
      const empty = el("div", "empty-state");
      empty.innerHTML = `
        <div class="empty-icon">${svg(ICONS.check, 20)}</div>
        <p>${activeFilter === "all" ? "No findings recorded for this target." : `No ${activeFilter} severity findings.`}</p>
      `;
      host.append(empty);
      return;
    }

    list.forEach((f) => host.append(createFindingElement(f)));
  }

  function renderFilters(counts) {
    const host = $("filters");
    if (!host) return;
    host.innerHTML = "";

    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    const options = [["all", "All", total]];
    ["critical", "high", "medium", "low", "info"].forEach((sev) => {
      if (counts[sev]) options.push([sev, sev, counts[sev]]);
    });

    options.forEach(([key, label, count]) => {
      const btn = el("button", null, `${label} · ${count}`);
      btn.type = "button";
      btn.setAttribute("aria-pressed", String(activeFilter === key));
      btn.addEventListener("click", () => {
        activeFilter = key;
        renderFilters(counts);
        renderFindings();
      });
      host.append(btn);
    });
  }

  function renderResults(payload) {
    currentResult = payload.result || payload;
    const r = currentResult;
    const counts = r.severity_counts || {};
    const total = Object.values(counts).reduce((a, b) => a + b, 0);

    const titleNode = $("resultsTitle");
    if (titleNode) titleNode.textContent = r.final_url || r.target_url;

    const metaNode = $("resultsMeta");
    if (metaNode) metaNode.textContent = `${total} findings · ${r.elapsed_seconds}s scan time · ${r.scanned_at}`;

    const pdfBtn = $("pdfBtn");
    if (pdfBtn) pdfBtn.href = url_(`/api/scan/${r.scan_id}/report.pdf`);

    const jsonBtn = $("jsonBtn");
    if (jsonBtn) jsonBtn.href = url_(`/api/scan/${r.scan_id}/report.json`);

    const stats = $("stats");
    if (stats) {
      stats.innerHTML = "";
      stats.append(renderKPI(counts.critical || 0, "Critical", "critical"));
      stats.append(renderKPI(counts.high || 0, "High", "high"));
      stats.append(renderKPI(counts.medium || 0, "Medium", "medium"));
      stats.append(renderKPI(total, "Total findings", "total"));
    }

    renderMix(counts);

    const sumNode = $("summary");
    if (sumNode) sumNode.textContent = r.executive_summary || "No executive summary available.";

    const risksList = $("topRisks");
    if (risksList) {
      risksList.innerHTML = "";
      (r.top_risks || []).forEach((risk) => risksList.append(el("li", null, risk)));
    }

    renderVitals(r.vitals);

    const stagesNode = $("stageSummary");
    if (stagesNode) {
      stagesNode.innerHTML = "";
      (r.stages || []).forEach((s) => {
        const row = el("div", "stage-row");
        row.append(el("span", null, STAGE_LABELS[s.key] || s.label));
        row.append(el("span", `stage-status ${s.status}`, `${s.status} · ${s.elapsed_seconds}s`));
        stagesNode.append(row);
      });
    }

    renderGallery(r.screenshots, r.scan_id);

    activeFilter = "all";
    renderFilters(counts);
    renderFindings();

    const s = r.safety || {};
    const recordNode = $("safetyList");
    if (recordNode) {
      recordNode.innerHTML = "";
      [
        `robots.txt: ${s.robots_txt || "verified"} (${s.robots_url || ""})`,
        `Throttled to one request every ${s.throttle_seconds || 1.5}s from ${s.user_agent || "SiteSentinel"}`,
        `Forms submitted: ${s.forms_submitted ?? 0}. ${s.forms_policy || "Read-only audit."}`,
        `AI checks: ${s.ai_model || "gemini-flash-latest"}. ${s.ai_model_policy || ""}`,
      ].forEach((line) => recordNode.append(el("li", null, line)));
    }

    show("results");
  }

  /* ─── Scan execution ──────────────────────────────────────────────────── */
  let activeEventSource = null;

  function setScanButtonState(loading) {
    const btn = $("scanBtn");
    if (!btn) return;
    btn.disabled = loading;
    const label = btn.querySelector(".scan-btn-label");
    const spinner = btn.querySelector(".scan-btn-spinner");
    const arrow = btn.querySelector(".scan-btn-arrow");
    if (label) label.textContent = loading ? "Starting…" : "Run scan";
    if (spinner) spinner.hidden = !loading;
    if (arrow) arrow.hidden = loading;
  }

  function showError(msg) {
    const err = $("errorMessage");
    if (err) err.textContent = msg;
    show("error");
    if (activeEventSource) {
      activeEventSource.close();
      activeEventSource = null;
    }
    clearInterval(timer);
    setScanButtonState(false);
  }

  async function startScan(targetUrl) {
    const landingErr = $("landingError");
    if (landingErr) landingErr.hidden = true;

    setScanButtonState(true);
    renderRail();

    const consoleBox = $("console");
    if (consoleBox) consoleBox.textContent = "";

    const progTitle = $("progressTitle");
    if (progTitle) progTitle.textContent = targetUrl;

    setProgress(3);

    const liveFind = $("liveFindings");
    if (liveFind) liveFind.textContent = "0";
    const liveStg = $("liveStages");
    if (liveStg) liveStg.textContent = `0 / ${STAGE_ORDER.length}`;
    const liveAct = $("liveActivity");
    if (liveAct) liveAct.textContent = "initializing…";

    liveIssues = 0;
    resetPreview();
    show("progress");
    startTimer();

    let scanId;
    try {
      const res = await fetch(url_("/api/scan"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: targetUrl }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Could not initialize the scan.");
      }
      scanId = data.scan_id;
    } catch (err) {
      setScanButtonState(false);
      showError(err.message || "Failed to reach the SiteSentinel engine.");
      return;
    }

    activeScanId = scanId;
    activeEventSource = new EventSource(url_(`/api/scan/${scanId}/events`));

    activeEventSource.onmessage = (e) => {
      let event;
      try {
        event = JSON.parse(e.data);
      } catch {
        return;
      }

      if (event.type === "log") {
        logLine(event.message);
      } else if (event.type === "stage") {
        updateStage(event);
      } else if (event.type === "robots") {
        const liveAct = $("liveActivity");
        if (liveAct) liveAct.textContent = "robots.txt verified";
        logLine("robots.txt verified — fail-closed policy passed");
      } else if (event.type === "preflight") {
        logLine(event.message);
      } else if (event.type === "done") {
        setProgress(100);

        if (activeEventSource) {
          activeEventSource.close();
          activeEventSource = null;
        }
        clearInterval(timer);
        setScanButtonState(false);
        // Brief pause so the dial reads 100% before the workspace appears.
        setTimeout(() => renderResults(event), REDUCED.matches ? 0 : 450);
      } else if (event.type === "error") {
        setScanButtonState(false);
        showError(event.message);
      }
    };

    activeEventSource.onerror = () => {
      if (!activeEventSource) return;
      activeEventSource.close();
      activeEventSource = null;
      clearInterval(timer);
      setScanButtonState(false);

      fetch(url_(`/api/scan/${scanId}`))
        .then((r) => r.json())
        .then((job) => {
          if (job.status === "done" && job.result) {
            renderResults(job);
          } else {
            showError(job.error || "Connection to the scanner dropped. The scan may have timed out.");
          }
        })
        .catch(() => showError("Connection lost to the scanner service."));
    };
  }

  /* ─── Boot ────────────────────────────────────────────────────────────── */
  document.addEventListener("DOMContentLoaded", () => {
    renderChecks();
    renderSteps();
    renderFacts();
    initReveal();
    initSpotlight();
    initTicker();
    checkHealth();

    const scanForm = $("scanForm");
    if (scanForm) {
      scanForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const urlInput = $("url");
        const val = urlInput ? urlInput.value.trim() : "";
        if (!val) {
          const err = $("landingError");
          if (err) {
            err.hidden = false;
            err.textContent = "Please enter a valid website URL to scan.";
          }
          if (urlInput) urlInput.focus();
          return;
        }
        startScan(val);
      });
    }

    ["cancelBtn", "errorRetry", "againBtn"].forEach((id) => {
      const btn = $(id);
      if (!btn) return;
      btn.addEventListener("click", () => {
        if (activeEventSource) {
          activeEventSource.close();
          activeEventSource = null;
        }
        clearInterval(timer);
        setScanButtonState(false);
        show("landing");
        const urlInput = $("url");
        if (urlInput) urlInput.focus();
      });
    });

    const lb = $("lightbox");
    if (lb) {
      lb.addEventListener("click", (e) => {
        if (e.target === lb || e.target.classList.contains("lightbox-close")) {
          closeLightbox();
        }
      });
    }

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        closeLightbox();
      }
    });

    const params = new URLSearchParams(window.location.search);
    const paramUrl = params.get("url");
    if (paramUrl) {
      const urlInput = $("url");
      if (urlInput) urlInput.value = paramUrl;
      startScan(paramUrl);
    }
  });
})();
