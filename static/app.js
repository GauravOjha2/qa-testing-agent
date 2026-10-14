/* ============================================================================
   SiteSentinel frontend — landing → dark console (SSE) → results.
   Plain HTML/CSS/JS, no build step. API base comes from app-config.js.
   ========================================================================== */

const API = (window.SENTINEL_API || "").replace(/\/$/, "");
const url_ = (path) => `${API}${path}`;
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};
const esc = (v) => String(v === null || v === undefined ? "" : v);
const svg = (paths, size) =>
  `<svg viewBox="0 0 24 24" width="${size || 19}" height="${size || 19}" aria-hidden="true">${paths}</svg>`;

/* ---------------------------------------------------------------- data ---- */

const ICONS = {
  layout: '<rect x="3" y="4" width="18" height="13" rx="2.2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M8 20h8M12 17v3" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><path d="M3 8.5h18" fill="none" stroke="currentColor" stroke-width="1.7"/>',
  a11y: '<circle cx="12" cy="4.6" r="2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M4.5 8.6c2.4.9 4.9 1.3 7.5 1.3s5.1-.4 7.5-1.3M12 9.9v4.3m0 0-3 6m3-6 3 6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
  speed: '<path d="M4 18a8 8 0 1 1 16 0" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><path d="m12 18 4.2-5.6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><circle cx="12" cy="18" r="1.6" fill="currentColor"/>',
  forms: '<rect x="3" y="5" width="18" height="14" rx="2.4" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M7 10h6M7 14h3" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><path d="m15 14 4-4" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  answer: '<path d="M4.5 6.5A2.5 2.5 0 0 1 7 4h10a2.5 2.5 0 0 1 2.5 2.5v6A2.5 2.5 0 0 1 17 15H9l-4.5 4v-12.5Z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M8.5 9.5h7M8.5 12h4" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  check: '<path d="m5 12.5 4.4 4.4L19 7" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>',
};

/* One hue per check — colour that carries meaning, not decoration. */
const CHECKS = [
  ["01", "Layout", "Full-page captures at phone, tablet and desktop, plus anything that scrolls sideways.",
    "layout", "#5b4bf5", "rgba(91,75,245,.10)", "rgba(91,75,245,.20)"],
  ["02", "Accessibility", "A WCAG 2.2 A/AA pass with the failing element quoted for every issue.",
    "a11y", "#0e8fb5", "rgba(14,165,233,.12)", "rgba(14,165,233,.22)"],
  ["03", "Speed", "Largest paint, layout shift and blocking time, measured on a mobile profile.",
    "speed", "#b5730a", "rgba(224,135,0,.12)", "rgba(224,135,0,.22)"],
  ["04", "Forms", "Every field filled with boundary, invalid and international values. Nothing is submitted.",
    "forms", "#c8384f", "rgba(229,72,77,.11)", "rgba(229,72,77,.22)"],
  ["05", "Answer engines", "Whether the page states what buyers ask, and where an answer engine would guess.",
    "answer", "#0b8f70", "rgba(11,157,99,.11)", "rgba(11,157,99,.22)"],
];

const STEPS = [
  ["01", "Paste a URL", "The scan reads robots.txt first. If it says no, or cannot be reached, nothing else happens."],
  ["02", "Watch it run", "Captures, audit, form probing and the answer-engine pass report their progress as they go."],
  ["03", "Take the report", "A PDF for the people who asked, and the raw JSON for the people who build."],
];

const FACTS = [
  ["robots.txt comes first", "Fetched before any page loads. Disallow stops the scan."],
  ["Forms are never submitted", "There is no submit path in the scanner, and every non-GET request is blocked."],
  ["One page, no crawl", "Only the URL you paste. Nothing else on the site is touched."],
  ["Nothing kept", "Captures and findings are deleted two hours after the scan."],
];

const STAGE_ORDER = [
  ["screenshots", "Captures", "Capture"],
  ["accessibility", "Accessibility", "Audit"],
  ["vitals", "Speed", "Audit"],
  ["forms", "Forms", "Guard"],
  ["ai", "Answer engines", "Intel"],
];
const STAGE_LABEL = Object.fromEntries(STAGE_ORDER.map((r) => [r[0], r[1]]));

const SEV_COLOR = { critical: "#d93025", high: "#c2410c", medium: "#a16207", low: "#0e6fd8", info: "#83838f" };

/* -------------------------------------------------------------- render --- */

function renderChecks() {
  const host = $("checkList");
  CHECKS.forEach((c) => {
    const li = el("li", "check");
    li.style.setProperty("--tone", c[4]);
    li.style.setProperty("--tint", c[5]);
    li.style.setProperty("--edge", c[6]);
    li.innerHTML =
      `<span class="idx mono">${c[0]}</span>
       <span class="tile">${svg(ICONS[c[3]])}</span>
       <h3>${esc(c[1])}</h3>
       <p>${esc(c[2])}</p>`;
    host.append(li);
  });
}

function renderSteps() {
  const host = $("stepList");
  STEPS.forEach((s) => {
    const li = el("li", "step");
    li.innerHTML = `<span class="num">${s[0]}</span><h3>${esc(s[1])}</h3><p>${esc(s[2])}</p>`;
    host.append(li);
  });
}

function renderFacts() {
  const host = $("factList");
  FACTS.forEach((f) => {
    const li = el("li", "fact");
    li.innerHTML =
      `<span class="tick">${svg(ICONS.check, 14)}</span>
       <dl><dt>${esc(f[0])}</dt><dd>${esc(f[1])}</dd></dl>`;
    host.append(li);
  });
}

/* --------------------------------------------------------------- views --- */

function show(view) {
  ["landing", "progress", "results", "error"].forEach((id) => {
    const node = $("view-" + id);
    const active = id === view;
    node.classList.toggle("is-active", active);
    node.hidden = !active;
  });
  window.scrollTo({ top: 0 });
}

async function checkHealth() {
  try {
    const res = await fetch(url_("/api/health"));
    if (!res.ok) return;
    const data = await res.json();
    if (!data.ai_enabled) {
      $("urlHelp").textContent = "Read-only · robots.txt respected · forms never submitted · answer-engine checks are off on this instance";
    }
  } catch (e) { /* cosmetic */ }
}

/* ------------------------------------------------------------ progress --- */

function renderRail() {
  const rail = $("stageList");
  rail.innerHTML = "";
  STAGE_ORDER.forEach((row) => {
    const li = el("li");
    li.dataset.key = row[0];
    li.dataset.status = "pending";
    li.append(el("span", "mark", "•"));
    const body = el("div");
    body.append(el("span", "label", row[1]));
    body.append(el("span", "detail", `queued · ${row[2]}`));
    li.append(body);
    li.append(el("span", "time", "–"));
    rail.append(li);
  });
}

let liveIssues = 0;

function updateStage(event) {
  const row = document.querySelector(`.rail li[data-key="${event.key}"]`);
  if (!row) return;
  row.dataset.status = event.status || "ok";
  row.querySelector(".mark").textContent =
    event.status === "ok" ? "✓" : event.status === "failed" ? "!" : event.status === "degraded" ? "~" : "•";
  const detail = row.querySelector(".detail");
  detail.textContent = event.detail || (event.status === "running" ? "running" : detail.textContent);
  if (typeof event.elapsed_seconds === "number") {
    row.querySelector(".time").textContent = `${event.elapsed_seconds}s`;
  }

  const settled = document.querySelectorAll('.rail li[data-status="ok"], .rail li[data-status="failed"], .rail li[data-status="degraded"]').length;
  const pct = Math.min(99, Math.round((settled / STAGE_ORDER.length) * 100));
  $("barFill").style.width = `${pct}%`;
  $("barTrack").setAttribute("aria-valuenow", String(pct));
  $("liveStages").textContent = `${settled}/${STAGE_ORDER.length}`;

  const label = STAGE_LABEL[event.key] || event.label;
  $("liveActivity").textContent = event.status === "running" ? label : `${label} · ${event.status}`;

  if (event.key === "screenshots" && event.status !== "running" && event.status !== "failed") {
    loadPreview(event.viewports);
  }
  if (typeof event.findings_total === "number" && event.findings_total !== liveIssues) {
    liveIssues = event.findings_total;
    countUp($("liveFindings"), liveIssues, 400);
  }
}

function logLine(message) {
  const box = $("console");
  box.append(document.createTextNode(`[${new Date().toLocaleTimeString([], { hour12: false })}] ${message}\n`));
  box.scrollTop = box.scrollHeight;
}

let activeScanId = null;
let previewLoaded = false;

function resetPreview() {
  const frame = $("previewFrame");
  frame.classList.remove("ready");
  $("previewImg").hidden = true;
  $("previewImg").removeAttribute("src");
  $("previewEmpty").textContent = "waiting for the first capture";
  $("previewBadge").textContent = "queued";
  $("previewMeta").textContent = "desktop · 1440px";
  previewLoaded = false;
}

function loadPreview(viewports) {
  if (previewLoaded || !activeScanId) return;
  previewLoaded = true;
  const probe = new Image();
  probe.onload = () => {
    const target = $("previewImg");
    target.src = probe.src;
    target.hidden = false;
    $("previewFrame").classList.add("ready");
    $("previewBadge").textContent = "captured";
    $("previewMeta").textContent = `live capture · ${viewports && viewports.length ? viewports.length : 1} viewports`;
  };
  probe.onerror = () => {
    previewLoaded = false;
    $("previewEmpty").textContent = "no capture available";
  };
  probe.src = url_(`/api/scan/${activeScanId}/shot/desktop.jpg?t=${Date.now()}`);
}

let timer = null;
function startTimer() {
  const t0 = Date.now();
  clearInterval(timer);
  timer = setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    $("elapsed").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }, 1000);
}

/* ------------------------------------------------------------- results --- */

function countUp(node, value, ms) {
  if (!node) return;
  ms = ms || 600;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    node.textContent = String(value);
    return;
  }
  const start = performance.now();
  const tick = (now) => {
    const p = Math.min(1, (now - start) / ms);
    node.textContent = String(Math.round(value * (1 - Math.pow(1 - p, 3))));
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function kpi(count, label, cls) {
  const wrap = el("div", `kpi ${cls}`);
  const n = el("div", "n", "0");
  wrap.append(n);
  wrap.append(el("div", "l", label));
  countUp(n, count);
  return wrap;
}

function renderMix(counts) {
  const host = $("mix");
  host.innerHTML = "";
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  host.append(el("div", "mix-title", "Severity mix"));
  const bar = el("div", "mix-bar");
  const legend = el("div", "mix-legend");
  ["critical", "high", "medium", "low", "info"].forEach((sev) => {
    const value = counts[sev] || 0;
    if (!value) return;
    const seg = el("span");
    seg.style.width = `${(value / total) * 100}%`;
    seg.style.background = SEV_COLOR[sev];
    bar.append(seg);
    const item = el("span");
    const dot = el("i");
    dot.style.background = SEV_COLOR[sev];
    item.append(dot, document.createTextNode(`${sev} ${value}`));
    legend.append(item);
  });
  host.append(bar, legend);
}

function vital(label, value, unit, bounds, decimals) {
  const wrap = el("div", "vital");
  if (value === null || value === undefined) {
    wrap.classList.add("warn");
    wrap.append(el("div", "v", "n/a"));
  } else {
    const shown = decimals !== undefined
      ? Number(value).toFixed(decimals)
      : unit === "" ? Number(value).toFixed(2) : `${Math.round(value)}${unit}`;
    wrap.append(el("div", "v", shown));
    if (bounds) wrap.classList.add(value > bounds[1] ? "bad" : value > bounds[0] ? "warn" : "good");
  }
  wrap.append(el("div", "k", label));
  return wrap;
}

function renderVitals(vitals) {
  const host = $("vitals");
  host.innerHTML = "";
  if (!vitals || !vitals.source) {
    host.append(el("p", null, "Vitals could not be measured in this run."));
    return;
  }
  host.append(vital("LCP", vitals.lcp_ms, "ms", [2500, 4000]));
  host.append(vital("CLS", vitals.cls, "", [0.1, 0.25]));
  host.append(vital("INP", vitals.inp_ms, "ms", [200, 500]));
  host.append(vital("TBT", vitals.tbt_ms, "ms", [200, 600]));
  if (vitals.performance_score !== null && vitals.performance_score !== undefined) {
    host.append(vital("Score", vitals.performance_score, "", null, 0));
  }
  host.append(el("p", null, `Measured with ${esc(vitals.source)}.${vitals.inp_note ? " " + esc(vitals.inp_note) : ""}`));
}

function renderGallery(shots, scanId) {
  const host = $("gallery");
  host.innerHTML = "";
  if (!shots || !shots.length) {
    host.append(el("p", "dim", "No captures for this run."));
    return;
  }
  shots.forEach((shot) => {
    const fig = el("figure", "shot");
    const link = el("a");
    link.href = url_(`/api/scan/${scanId}/shot/${shot.viewport}.png`);
    link.target = "_blank";
    link.rel = "noopener";
    const img = el("img");
    img.src = url_(`/api/scan/${scanId}/shot/${shot.viewport}.jpg`);
    img.alt = `${shot.viewport} capture of the scanned page`;
    img.loading = "lazy";
    link.append(img);
    const cap = el("figcaption");
    cap.append(el("span", null, `${shot.viewport} · ${shot.width}×${shot.height}`));
    cap.append(el("span", `chip ${shot.overflow_x ? "warn" : "ok"}`,
      shot.overflow_x ? `+${shot.overflow_px}px wide` : "fits"));
    fig.append(link, cap);
    host.append(fig);
  });
}

function evidence(ev) {
  const box = el("div", "ev");
  Object.entries(ev || {}).forEach((entry) => {
    const text = String(entry[1] === null || entry[1] === undefined ? "" : entry[1]).trim();
    if (!text) return;
    const row = el("div");
    row.append(el("b", null, entry[0]));
    row.append(el("span", null, text.length > 320 ? text.slice(0, 320) + "…" : text));
    box.append(row);
  });
  return box;
}

function finding(f) {
  const item = el("details", `finding ${f.severity}`);
  const summary = el("summary");
  summary.append(el("span", "sev", f.severity.toUpperCase()));
  summary.append(el("span", "title", f.title));
  summary.append(el("span", "meta", `${f.category} · ${f.id}`));
  item.append(summary);

  const body = el("div", "body");
  if (f.detail) body.append(el("p", null, f.detail));
  if (f.evidence && Object.keys(f.evidence).length) body.append(evidence(f.evidence));
  if (f.recommendation) {
    const rec = el("p", "rec");
    rec.append(el("strong", null, "Fix: "));
    rec.append(document.createTextNode(f.recommendation));
    body.append(rec);
  }
  item.append(body);
  return item;
}

let currentResult = null;
let filter = "all";

function renderFindings() {
  const host = $("findings");
  host.innerHTML = "";
  const rows = ((currentResult && currentResult.findings) || []).filter(
    (f) => filter === "all" || f.severity === filter
  );
  if (!rows.length) {
    const empty = el("div", "empty");
    empty.innerHTML = `<span class="glyph">${svg(ICONS.check, 20)}</span>`;
    empty.append(el("p", null, filter === "all"
      ? "Nothing in this run met a reporting threshold."
      : `No ${filter} findings.`));
    host.append(empty);
    return;
  }
  rows.forEach((f) => host.append(finding(f)));
}

function renderFilters(counts) {
  const host = $("filters");
  host.innerHTML = "";
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const options = [["all", "All", total]];
  ["critical", "high", "medium", "low", "info"].forEach((sev) => {
    if (counts[sev]) options.push([sev, sev, counts[sev]]);
  });
  options.forEach((opt) => {
    const btn = el("button", null, `${opt[1]} ${opt[2]}`);
    btn.type = "button";
    btn.setAttribute("aria-pressed", String(filter === opt[0]));
    btn.addEventListener("click", () => {
      filter = opt[0];
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

  $("resultsTitle").textContent = r.final_url || r.target_url;
  $("resultsMeta").textContent = `${total} findings · ${r.elapsed_seconds}s · ${r.scanned_at}`;
  $("pdfBtn").href = url_(`/api/scan/${r.scan_id}/report.pdf`);
  $("jsonBtn").href = url_(`/api/scan/${r.scan_id}/report.json`);

  const stats = $("stats");
  stats.innerHTML = "";
  stats.append(kpi(counts.critical || 0, "Critical", "critical"));
  stats.append(kpi(counts.high || 0, "High", "high"));
  stats.append(kpi(counts.medium || 0, "Medium", "medium"));
  stats.append(kpi(total, "Total", "total"));
  renderMix(counts);

  $("summary").textContent = r.executive_summary || "–";
  const risks = $("topRisks");
  risks.innerHTML = "";
  (r.top_risks || []).forEach((risk) => risks.append(el("li", null, risk)));

  renderVitals(r.vitals);

  const stages = $("stageSummary");
  stages.innerHTML = "";
  (r.stages || []).forEach((s) => {
    const li = el("li");
    li.append(el("span", null, STAGE_LABEL[s.key] || s.label));
    li.append(el("span", `st ${s.status}`, `${s.status} · ${s.elapsed_seconds}s`));
    stages.append(li);
  });

  renderGallery(r.screenshots, r.scan_id);
  filter = "all";
  renderFilters(counts);
  renderFindings();

  const s = r.safety || {};
  const record = $("safetyList");
  record.innerHTML = "";
  [
    `robots.txt: ${s.robots_txt || "verified"} (${s.robots_url || ""})`,
    `One request every ${s.throttle_seconds}s from ${s.user_agent}`,
    `Forms submitted: ${s.forms_submitted}. ${s.forms_policy}`,
    `Answer-engine checks ran on ${s.ai_model}. ${s.ai_model_policy}`,
  ].forEach((line) => record.append(el("li", null, line)));

  show("results");
}

/* ---------------------------------------------------------------- flow --- */

function resetButton() {
  const btn = $("scanBtn");
  btn.disabled = false;
  btn.querySelector(".btn-label").textContent = "Run scan";
}

let source = null;

function showError(message) {
  $("errorMessage").textContent = message;
  show("error");
  if (source) { source.close(); source = null; }
  clearInterval(timer);
}

async function startScan(url) {
  $("landingError").hidden = true;
  $("scanBtn").disabled = true;
  $("scanBtn").querySelector(".btn-label").textContent = "Starting";
  renderRail();
  $("console").textContent = "";
  $("progressUrl").textContent = url;
  $("barFill").style.width = "2%";
  $("barTrack").setAttribute("aria-valuenow", "2");
  $("liveFindings").textContent = "0";
  $("liveStages").textContent = `0/${STAGE_ORDER.length}`;
  $("liveActivity").textContent = "starting";
  liveIssues = 0;
  resetPreview();
  show("progress");
  startTimer();

  let scanId;
  try {
    const res = await fetch(url_("/api/scan"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not start the scan.");
    scanId = data.scan_id;
  } catch (err) {
    resetButton();
    showError(err.message || "Could not reach the scanner.");
    return;
  }

  activeScanId = scanId;
  source = new EventSource(url_(`/api/scan/${scanId}/events`));
  source.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "log") logLine(event.message);
    else if (event.type === "stage") updateStage(event);
    else if (event.type === "robots") $("liveActivity").textContent = "robots.txt verified";
    else if (event.type === "preflight") logLine(event.message);
    else if (event.type === "done") {
      $("barFill").style.width = "100%";
      $("barTrack").setAttribute("aria-valuenow", "100");
      source.close(); source = null;
      clearInterval(timer);
      resetButton();
      renderResults(event);
    } else if (event.type === "error") {
      resetButton();
      showError(event.message);
    }
  };
  source.onerror = () => {
    if (!source) return;
    source.close(); source = null;
    clearInterval(timer);
    resetButton();
    fetch(url_(`/api/scan/${scanId}`))
      .then((r) => r.json())
      .then((job) => {
        if (job.status === "done" && job.result) renderResults(job);
        else showError(job.error || "The progress stream dropped. The scan may still be running.");
      })
      .catch(() => showError("Lost connection to the scanner."));
  };
}

/* -------------------------------------------------------------- wiring --- */

renderChecks();
renderSteps();
renderFacts();
checkHealth();

$("scanForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const url = $("url").value.trim();
  if (!url) {
    $("landingError").hidden = false;
    $("landingError").textContent = "Enter a URL to scan.";
    $("url").focus();
    return;
  }
  startScan(url);
});

["cancelBtn", "errorRetry", "againBtn"].forEach((id) => {
  $(id).addEventListener("click", () => {
    if (source) { source.close(); source = null; }
    clearInterval(timer);
    resetButton();
    show("landing");
    $("url").focus();
  });
});

const params = new URLSearchParams(window.location.search);
if (params.get("url")) {
  $("url").value = params.get("url");
  startScan(params.get("url"));
}
