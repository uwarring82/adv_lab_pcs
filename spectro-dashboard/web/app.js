"use strict";
// Dashboard logic: talk to the local FastAPI service, plot with uPlot.
// Figures follow the lab's earlier USB2000 analysis notebook:
// mean with grey +-SEM, red saturation line at 2^16, channel-number x axis,
// channels 0-1 hidden, y fixed to 0..2^16 unless autoscaled, optional log y,
// and a per-channel intensity histogram (tab:blue bars, black edges).

const $ = (id) => document.getElementById(id);
const SAT = 2 ** 16;
const C0 = "#1f77b4";                      // matplotlib tab:blue
const MARK = "#ff7f0e";                    // matplotlib tab:orange (selected channel)
const FONT = '12px "DejaVu Sans", Verdana, sans-serif';
const AXIS = {
  stroke: "#000",
  font: FONT,
  labelFont: '13px "DejaVu Sans", Verdana, sans-serif',
  grid: { stroke: "#b0b0b0", width: 0.8 },
  ticks: { stroke: "#000", width: 1, size: 4 },
};
const MAIN_H = 340, HIST_H = 180, STRIP_H = 40;
const GAMMA = 0.8;                         // intensity gamma of the colour strip, as in the lab's earlier code

const state = {
  data: null,          // {wavelengths, intensities, sem} currently shown
  measurement: null,   // last measurement summary from the server
  xAxis: "channel",
  logY: false,
  autoY: false,
  band: true,
  strip: true,         // colour illustration of the visible spectrum
  config: null,        // last acquisition config confirmed by the server
  xZoom: null,        // [min, max] of the x window, kept across live frames
  channel: null,       // channel selected for the histogram
  histLog: false,
  hist: null,
  live: false,
  ws: null,
  busy: false,
};
let plot = null, hplot = null;
const dpr = () => window.devicePixelRatio || 1;

// --- HTTP helpers -------------------------------------------------------------
// Server errors carry {"detail": "..."} (422 invalid request, 409 device busy);
// pydantic validation errors carry a list of {loc, msg}.
async function errorText(r) {
  const body = await r.text();
  try {
    const d = JSON.parse(body).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(-1)[0]}: ${e.msg}`).join("; ");
  } catch { /* not JSON */ }
  return `${r.status} ${body}`;
}
async function api(method, url, body) {
  const r = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}
const getJSON = (url) => api("GET", url);
const postJSON = (url, body) => api("POST", url, body);

let noticeTimer = null;
function notify(msg, kind = "info") {
  const el = $("notice");
  el.textContent = msg;
  el.className = `notice ${kind}`;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { el.textContent = ""; el.className = "notice"; }, kind === "error" ? 12000 : 6000);
}
// Run an action from a button; show a failure instead of dropping it silently.
const guarded = (fn) => () => fn().catch((err) => notify(err.message, "error"));

// --- Main spectrum figure -------------------------------------------------
function yRange(u, min, max) {
  // min/max are over the data visible in the current x window.
  const fixed = state.logY ? [1, SAT * 1.6] : [0, SAT * 1.03];
  if (!state.autoY || min == null || !isFinite(min) || !isFinite(max)) return fixed;
  if (state.logY) return [Math.max(min, 1) / 1.5, Math.max(max, 1) * 1.5];
  const pad = (max - min) * 0.05 || 1;
  return [min - pad, max + pad];
}

function drawOverlays(u) {
  const ctx = u.ctx;
  const { left, top, width, height } = u.bbox;
  ctx.save();
  ctx.beginPath();
  ctx.rect(left, top, width, height);
  ctx.clip();
  // Saturation level of the 16-bit ADC, red and heavy as in the notebook.
  const ys = u.valToPos(SAT, "y", true);
  ctx.strokeStyle = "red";
  ctx.lineWidth = 3 * dpr();
  ctx.beginPath();
  ctx.moveTo(left, ys);
  ctx.lineTo(left + width, ys);
  ctx.stroke();
  // Selected channel.
  if (state.channel != null && u.data[0].length > state.channel) {
    const xs = u.valToPos(u.data[0][state.channel], "x", true);
    ctx.strokeStyle = MARK;
    ctx.lineWidth = 1.5 * dpr();
    ctx.setLineDash([5 * dpr(), 4 * dpr()]);
    ctx.beginPath();
    ctx.moveTo(xs, top);
    ctx.lineTo(xs, top + height);
    ctx.stroke();
  }
  ctx.restore();
}

// --- Colour illustration of the visible spectrum ----------------------------
// Port of plot_spectrum_with_visual from the lab's earlier Python code: each visible channel gets
// its CIE 1931 sRGB colour scaled by (I / I_max)^0.8, with I_max taken over the
// visible channels in the current x window. Drawn under the main plot, sharing
// its x axis (zoom, channel/wavelength).
let rgbCache = { key: null, rgb: null };
function channelRGB(wl) {
  const key = `${wl.length}:${wl[0]}:${wl[wl.length - 1]}`;
  if (rgbCache.key !== key) {
    const rgb = new Float32Array(wl.length * 3);
    wl.forEach((w, i) => rgb.set(SpectrumColor.wavelengthToRGB(w), 3 * i));
    rgbCache = { key, rgb };
  }
  return rgbCache.rgb;
}

function nearest(xs, v) {  // index of the x value closest to v (xs ascending)
  let lo = 0, hi = xs.length - 1;
  if (v <= xs[lo]) return lo;
  if (v >= xs[hi]) return hi;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] <= v) lo = mid; else hi = mid;
  }
  return v - xs[lo] < xs[hi] - v ? lo : hi;
}

const stripRow = document.createElement("canvas");
function drawStrip(u) {
  const d = state.data, xs = u.data[0];
  const show = state.strip && d && xs && xs.length > 0;
  $("stripwrap").hidden = !show;
  if (!show) return;

  const r = dpr();
  const cssW = Math.round(u.bbox.width / r);
  $("striplabel").style.width = `${u.bbox.left / r}px`;  // align with the plot area
  const cv = $("strip");
  cv.style.width = `${cssW}px`;
  cv.style.height = `${STRIP_H}px`;
  cv.width = Math.round(cssW * r);
  cv.height = Math.round(STRIP_H * r);

  const [v0, v1] = SpectrumColor.VISIBLE;
  const wl = d.wavelengths, I = d.intensities, base = channelRGB(wl);
  const xmin = u.scales.x.min, xmax = u.scales.x.max;
  let imax = 0;
  for (let i = 2; i < xs.length; i++) {
    if (xs[i] >= xmin && xs[i] <= xmax && wl[i] >= v0 && wl[i] <= v1 && I[i] > imax) imax = I[i];
  }

  // One row of pixels, one colour per screen column, stretched to the strip height.
  const W = cv.width, img = new ImageData(W, 1), px = img.data;
  let firstVis = -1, lastVis = -1;
  for (let c = 0; c < W; c++) {
    const i = nearest(xs, u.posToVal((c + 0.5) / r, "x"));
    let R = 225, G = 225, B = 225;  // outside the visible range: neutral grey
    if (wl[i] >= v0 && wl[i] <= v1) {
      const k = imax > 0 ? Math.pow(Math.max(I[i], 0) / imax, GAMMA) * 255 : 0;
      R = base[3 * i] * k; G = base[3 * i + 1] * k; B = base[3 * i + 2] * k;
      if (firstVis < 0) firstVis = c;
      lastVis = c;
    }
    px[4 * c] = R; px[4 * c + 1] = G; px[4 * c + 2] = B; px[4 * c + 3] = 255;
  }
  stripRow.width = W;
  stripRow.height = 1;
  stripRow.getContext("2d").putImageData(img, 0, 0);
  const ctx = cv.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(stripRow, 0, 0, W, cv.height);

  // Name the invisible parts of the range.
  ctx.fillStyle = "#6b7380";
  ctx.font = `${11 * r}px "DejaVu Sans", Verdana, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const y = cv.height / 2, minW = 30 * r;
  if (firstVis < 0) {
    const mid = wl[nearest(xs, (xmin + xmax) / 2)];
    ctx.fillText(mid < v0 ? "UV (not visible)" : "IR (not visible)", W / 2, y);
  } else {
    if (firstVis > minW) ctx.fillText("UV", firstVis / 2, y);
    if (W - 1 - lastVis > minW) ctx.fillText("IR", (lastVis + W) / 2, y);
  }
}

function showCursor(u) {
  const i = u.cursor.idx, d = state.data;
  if (i == null || !d) return;
  const m = d.intensities[i], s = d.sem ? d.sem[i] : 0;
  $("readout").textContent =
    `channel ${i} · ${d.wavelengths[i].toFixed(2)} nm · ${m.toFixed(1)} ± ${s.toFixed(1)} counts` +
    "   (click: histogram · drag: zoom · double-click: reset)";
}

function buildMain() {
  if (plot) plot.destroy();
  state.xZoom = null;
  const el = $("plot");
  plot = new uPlot({
    width: el.clientWidth || 900,
    height: MAIN_H,
    legend: { show: false },
    cursor: { drag: { x: true, y: false, setScale: true }, points: { show: false } },
    scales: {
      x: { time: false, range: (u, min, max) => [min, max] },
      y: { distr: state.logY ? 3 : 1, range: yRange },
    },
    axes: [
      { ...AXIS, label: state.xAxis === "wavelength" ? "Wavelength (nm)" : "Channel number" },
      { ...AXIS, label: state.logY ? "Intensity (log scale)" : "Intensity (a.u.)", size: 66 },
    ],
    series: [
      {},
      { label: "+SEM", stroke: "rgba(128,128,128,0.6)", width: 0.6, points: { show: false } },
      { label: "-SEM", stroke: "rgba(128,128,128,0.6)", width: 0.6, points: { show: false } },
      { label: "mean", stroke: C0, width: 1.2, points: { show: false } },  // plain line, like fmt='-'
    ],
    bands: [{ series: [1, 2], fill: "rgba(128,128,128,0.3)" }],
    hooks: {
      setCursor: [showCursor],
      draw: [drawOverlays, drawStrip],
      setScale: [(u, key) => { if (key === "x") state.xZoom = [u.scales.x.min, u.scales.x.max]; }],
    },
  }, [[], [], [], []], el);

  // Click selects a channel; ignore the click that ends a drag-zoom.
  let down = null;
  plot.over.addEventListener("mousedown", (e) => { down = [e.clientX, e.clientY]; });
  plot.over.addEventListener("click", (e) => {
    if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    if (plot.cursor.idx != null) selectChannel(plot.cursor.idx);
  });
}

function mainData(d) {
  const n = d.intensities.length;
  const x = state.xAxis === "wavelength" ? d.wavelengths : Array.from({ length: n }, (_, i) => i);
  const showBand = state.band && d.sem && d.sem.some((v) => v > 0);
  const up = new Array(n), lo = new Array(n), m = new Array(n);
  for (let i = 0; i < n; i++) {
    if (i < 2) { up[i] = lo[i] = m[i] = null; continue; }  // channels 0-1 excluded, as in the notebook
    const v = d.intensities[i];
    const s = showBand ? d.sem[i] : 0;
    m[i] = v;
    up[i] = showBand ? v + s : null;
    lo[i] = showBand ? v - s : null;
    if (state.logY) {           // log axis: drop non-positive values, clamp the band floor
      if (m[i] <= 0) m[i] = null;
      if (up[i] != null && up[i] <= 0) up[i] = null;
      if (lo[i] != null) lo[i] = Math.max(lo[i], 0.5);
    }
  }
  return [x, up, lo, m];
}

function render(d, title) {
  state.data = d;
  if (title) $("source").textContent = title;
  if (!plot) buildMain();
  const data = mainData(d);
  plot.setData(data, false);
  const x = data[0];
  const [a, b] = state.xZoom || [x[0], x[x.length - 1]];
  plot.setScale("x", { min: a, max: b });  // also re-ranges y over the visible window
}

function rebuildMain() {
  buildMain();
  if (state.data) render(state.data);
}

// --- Histogram figure -----------------------------------------------------
function drawHist(h) {
  state.hist = h;
  if (hplot) hplot.destroy();
  const el = $("hplot");
  const e = h.bin_edges;
  const ymax = Math.max(1, ...h.counts);
  const y = h.counts.map((c) => (state.histLog && c <= 0 ? null : c));
  hplot = new uPlot({
    width: el.clientWidth || 600,
    height: HIST_H,
    legend: { show: false },
    cursor: { drag: { x: false, y: false }, points: { show: false } },
    scales: {
      x: { time: false, range: () => [e[0], e[e.length - 1]] },
      y: { distr: state.histLog ? 3 : 1, range: () => (state.histLog ? [0.8, ymax * 2] : [0, ymax * 1.05]) },
    },
    axes: [
      { ...AXIS, label: "Intensity (a.u.)" },
      {
        ...AXIS, label: state.histLog ? "Counts (log scale)" : "Counts", size: 54,
        incrs: [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000],  // counts are integers
      },
    ],
    series: [
      {},
      {
        stroke: "#000", width: 1, fill: "rgba(31,119,180,0.75)",
        paths: uPlot.paths.bars({ size: [1, Infinity], align: 1 }),  // align=1: bar starts at the left bin edge
        points: { show: false },
      },
    ],
    hooks: {
      setCursor: [(u) => {
        const i = u.cursor.idx;
        if (i == null) return;
        $("hstats").textContent = `${statsLine(h)}   ·   bin [${e[i].toFixed(1)}, ${e[i + 1].toFixed(1)}): ${h.counts[i]}`;
      }],
    },
  }, [e.slice(0, -1), y], el);
  $("htitle").textContent = `Intensity Histogram for Channel ${h.channel}`;
  $("hstats").textContent = statsLine(h);
}

function statsLine(h) {
  return `λ = ${h.wavelength_nm.toFixed(2)} nm · N = ${h.num_scans} · mean ${h.mean.toFixed(1)} · ` +
         `σ ${h.std.toFixed(2)} · SEM ${h.sem.toFixed(2)} counts · ${h.counts.length} bins`;
}

async function selectChannel(i) {
  const n = state.data ? state.data.intensities.length : 2048;
  i = Math.max(0, Math.min(n - 1, i | 0));
  state.channel = i;
  $("channel").value = i;
  if (plot) plot.redraw(false, false);
  if (!state.measurement) {
    $("htitle").textContent = `Intensity Histogram for Channel ${i}`;
    $("hstats").textContent = "Run a measurement to see this channel's histogram.";
    return;
  }
  try {
    drawHist(await getJSON(`/api/measurement/histogram?channel=${i}`));
  } catch (err) {
    $("hstats").textContent = "Histogram failed: " + err.message;
  }
}

// --- Live & single shot ---------------------------------------------------
function liveTitle(cfg) {
  return `Live · ${cfg.integration_time_ms} ms · average ${cfg.scans_to_average}` +
         (cfg.boxcar_width ? ` · boxcar ±${cfg.boxcar_width}` : "") +
         (cfg.subtract_dark ? " · dark subtracted" : "");
}
function showSpectrum(s) {
  render({ wavelengths: s.wavelengths, intensities: s.intensities, sem: s.sem }, liveTitle(s.config));
}
async function single() {
  showSpectrum(await getJSON("/api/spectrum"));
}
function startLive() {
  const proto = location.protocol === "https:" ? "wss://" : "ws://";
  const ws = new WebSocket(proto + location.host + "/ws/stream");
  ws.onmessage = (ev) => showSpectrum(JSON.parse(ev.data));
  ws.onclose = () => { if (state.live) stopLive(); };
  state.ws = ws;
  state.live = true;
  $("live").textContent = "Stop live";
  $("live").classList.add("on");
  $("badge").classList.add("live");
}
function stopLive() {
  state.live = false;
  if (state.ws) { state.ws.close(); state.ws = null; }
  $("live").textContent = "Start live";
  $("live").classList.remove("on");
  $("badge").classList.remove("live");
}

// --- Measurement ----------------------------------------------------------
function setBusy(b) {
  state.busy = b;
  for (const id of ["measure", "apply", "live", "single", "dark", "cleardark"]) $(id).disabled = b;
}
async function measure() {
  const n = parseInt($("nscans").value, 10) || 200;
  if (state.live) stopLive();
  setBusy(true);
  $("pbar").style.width = "0%";
  const poll = setInterval(async () => {
    try {
      const p = await getJSON("/api/measurement/progress");
      if (p.total) {
        $("pbar").style.width = `${(100 * p.done) / p.total}%`;
        $("msummary").textContent = `Measuring… ${p.done} / ${p.total} scans`;
      }
    } catch { /* keep polling */ }
  }, 250);
  try {
    showMeasurement(await postJSON("/api/measurement", { num_scans: n }));
  } catch (err) {
    $("msummary").textContent = "Measurement failed: " + err.message;
  } finally {
    clearInterval(poll);
    setBusy(false);
  }
}
function showMeasurement(m) {
  state.measurement = m;
  $("pbar").style.width = "100%";
  render({ wavelengths: m.wavelengths, intensities: m.mean, sem: m.sem },
         `Measurement · N = ${m.num_scans} scans · ${m.config.integration_time_ms} ms`);
  $("mcsv").disabled = false;
  const t = new Date(m.timestamp * 1000).toLocaleTimeString();
  $("msummary").textContent =
    `N = ${m.num_scans} scans at ${m.config.integration_time_ms} ms (${t}), shown above as mean ± SEM.`;
  if (state.channel == null) {             // default: the brightest channel
    let best = 2;
    for (let i = 2; i < m.mean.length; i++) if (m.mean[i] > m.mean[best]) best = i;
    state.channel = best;
  }
  selectChannel(state.channel);
}

// --- Config & status ------------------------------------------------------
function fillConfig(cfg) {
  state.config = cfg;
  $("integration").value = cfg.integration_time_ms;
  $("average").value = cfg.scans_to_average;
  $("boxcar").value = cfg.boxcar_width;
  $("subdark").checked = cfg.subtract_dark;
}
async function applyConfig() {
  const form = {
    integration_time_ms: parseFloat($("integration").value),
    scans_to_average: parseInt($("average").value, 10),
    boxcar_width: parseInt($("boxcar").value, 10),
    subtract_dark: $("subdark").checked,
  };
  // Send only what changed: a new integration time with "Subtract dark" still
  // ticked from before should switch subtraction off (server notice), not be
  // rejected for lacking a dark spectrum at the new exposure.
  const body = {};
  for (const [k, v] of Object.entries(form)) if (!state.config || state.config[k] !== v) body[k] = v;
  if (Object.keys(body).length === 0) {
    notify("No changes to apply.");
    if (!state.live) await single();
    return;
  }
  let cfg;
  try {
    cfg = await postJSON("/api/config", body);
  } catch (err) {  // rejected as a whole: show the settings that are actually active
    notify(err.message, "error");
    fillConfig(await getJSON("/api/config"));
    return;
  }
  fillConfig(cfg);
  notify(cfg.notice || "Settings applied.", cfg.notice ? "warn" : "info");
  if (!state.live) await single();
}
async function storeDark() {
  const d = await postJSON("/api/dark");
  notify(`Dark spectrum stored (${d.integration_time_ms} ms, ${d.scans} scan${d.scans > 1 ? "s" : ""}). ` +
         "Tick Subtract dark and Apply to use it.");
}
async function clearDark() {
  await api("DELETE", "/api/dark");
  fillConfig(await getJSON("/api/config"));  // the server switched subtraction off
  notify("Dark spectrum cleared.");
  if (!state.live) await single();
}

function renderSnippet() {
  $("snippet").textContent = [
    "import requests",
    `base = "${location.origin}"`,
    "",
    "# one live spectrum (list index = channel)",
    's = requests.get(base + "/api/spectrum").json()',
    'wl, I, dI = s["wavelengths"], s["intensities"], s["sem"]',
    "",
    "# N raw scans -> mean and SEM per channel",
    'm = requests.post(base + "/api/measurement",',
    '                  json={"num_scans": 200}).json()',
    'h = requests.get(base + "/api/measurement/histogram",',
    '                 params={"channel": 616}).json()',
  ].join("\n");
}

async function init() {
  renderSnippet();
  const { info, config } = await getJSON("/api/status");
  fillConfig(config);
  $("channel").max = info.pixels - 1;
  $("integration").min = info.integration_time_min_ms;
  $("integration").max = info.integration_time_max_ms;
  $("average").max = info.limits.max_scans_to_average;
  $("boxcar").max = info.limits.max_boxcar_width;
  $("nscans").max = info.limits.max_scans;
  const badge = $("badge");
  if (info.simulated) {
    badge.textContent = "SIMULATED" + (info.fallback_reason ? " (no hardware found)" : "");
    badge.className = "badge sim";
    if (info.fallback_reason) badge.title = info.fallback_reason;
  } else {
    badge.textContent = info.model + (info.serial ? ` · ${info.serial}` : "");
  }
  if (info.has_measurement) showMeasurement(await getJSON("/api/measurement"));
  else await single();
}

// --- Wiring ---------------------------------------------------------------
$("apply").onclick = guarded(applyConfig);
$("single").onclick = guarded(single);
$("live").onclick = () => (state.live ? stopLive() : startLive());
$("dark").onclick = guarded(storeDark);
$("cleardark").onclick = guarded(clearDark);
$("csv").onclick = () => { window.location = "/api/spectrum.csv"; };
$("measure").onclick = measure;
$("mcsv").onclick = () => { window.location = "/api/measurement.csv"; };
$("channel").onchange = (e) => selectChannel(parseInt(e.target.value, 10));
$("loghist").onchange = (e) => { state.histLog = e.target.checked; if (state.hist) drawHist(state.hist); };
$("logy").onchange = (e) => { state.logY = e.target.checked; rebuildMain(); };
$("autoy").onchange = (e) => { state.autoY = e.target.checked; if (state.data) render(state.data); };
$("band").onchange = (e) => { state.band = e.target.checked; if (state.data) render(state.data); };
$("color").onchange = (e) => { state.strip = e.target.checked; if (plot) drawStrip(plot); };
for (const r of document.querySelectorAll('input[name="xaxis"]')) {
  r.onchange = (e) => { state.xAxis = e.target.value; rebuildMain(); };
}
window.addEventListener("resize", () => {
  if (plot) plot.setSize({ width: $("plot").clientWidth, height: MAIN_H });
  if (hplot) hplot.setSize({ width: $("hplot").clientWidth, height: HIST_H });
});

init().catch((err) => {
  $("badge").textContent = "server unreachable";
  $("readout").textContent = "Could not reach the local service: " + err.message;
});
