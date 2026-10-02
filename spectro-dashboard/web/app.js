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
// x axis: no 2.5/25 steps, and plain numbers ("1000", not "1.000", which reads like a
// decimal in German); whole numbers unless zoomed in to a few nm.
const WL_INCRS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];
const CH_INCRS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];
function xTicks(u, splits, axisIdx, space, incr) {
  const d = incr >= 1 ? 0 : incr >= 0.1 ? 1 : 2;
  return splits.map((v) => v.toLocaleString(undefined,
    { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: false }));
}
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
  calActive: "factory", // wavelength calibration in use
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
      {
        ...AXIS, space: 60, values: xTicks,
        incrs: state.xAxis === "wavelength" ? WL_INCRS : CH_INCRS,
        label: xLabel(),
      },
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
      setScale: [(u, key) => {
        if (key !== "x") return;
        state.xZoom = [u.scales.x.min, u.scales.x.max];
        showZoom(u);
      }],
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

// The axis says which calibration the wavelengths come from.
function xLabel() {
  if (state.xAxis !== "wavelength") return "Channel number";
  if (state.source === "example") return "Wavelength (nm) · as recorded";
  return state.calActive === "custom" ? "Wavelength (nm) · custom calibration" : "Wavelength (nm)";
}

function render(d, title) {
  state.data = d;
  if (title) $("source").textContent = title;
  if (!plot || plot.axes[0].label !== xLabel()) buildMain();
  const data = mainData(d);
  plot.setData(data, false);
  const x = data[0];
  const [a, b] = state.xZoom || [x[0], x[x.length - 1]];
  plot.setScale("x", { min: a, max: b });  // also re-ranges y over the visible window
}

// --- Zoom controls under the plot -------------------------------------------
function showZoom(u) {
  const d = state.xAxis === "wavelength" ? 1 : 0;
  for (const [id, v] of [["xmin", u.scales.x.min], ["xmax", u.scales.x.max]]) {
    const el = $(id);
    if (document.activeElement !== el && v != null) el.value = v.toFixed(d);  // not while typing
  }
  $("xunit").textContent = state.xAxis === "wavelength" ? "nm" : "channel";
}
function applyZoom() {
  const a = parseFloat($("xmin").value), b = parseFloat($("xmax").value);
  if (!plot) return;
  if (!(a < b)) { notify("Zoom: 'from' must be smaller than 'to'.", "error"); return; }
  plot.setScale("x", { min: a, max: b });
}
function resetZoom() {
  if (!plot || !plot.data[0].length) return;
  const x = plot.data[0];
  plot.setScale("x", { min: x[0], max: x[x.length - 1] });
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
  return `λ = ${h.wavelength_nm.toFixed(2)} nm · N = ${h.num_scans} · raw counts: mean ${h.mean.toFixed(1)} · ` +
         `σ ${h.std.toFixed(2)} · SEM ${h.sem.toFixed(2)} · ${h.counts.length} bins`;
}

async function selectChannel(i) {
  const n = state.data ? state.data.intensities.length : 2048;
  i = Math.max(0, Math.min(n - 1, i | 0));
  state.channel = i;
  $("channel").value = i;
  if (plot) plot.redraw(false, false);
  if (state.source === "example") {
    $("htitle").textContent = `Intensity Histogram for Channel ${i}`;
    $("hstats").textContent = "Example spectra contain mean and SEM only, no single scans for a histogram.";
    return;
  }
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
  leaveExample();
  state.source = "live";
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
  leaveExample();
  state.source = "measurement";
  state.measurement = m;
  $("pbar").style.width = "100%";
  const dark = m.dark_subtracted ? " · dark subtracted" : "";
  render({ wavelengths: m.wavelengths, intensities: m.mean, sem: m.sem },
         `Measurement · N = ${m.num_scans} scans · ${m.config.integration_time_ms} ms${dark}`);
  $("mcsv").disabled = false;
  const t = new Date(m.timestamp * 1000).toLocaleTimeString();
  $("msummary").textContent =
    `N = ${m.num_scans} scans at ${m.config.integration_time_ms} ms (${t}), shown above as mean ± SEM` +
    (m.dark_subtracted ? `, minus the dark spectrum (${m.dark_scans} scan${m.dark_scans > 1 ? "s" : ""}).` : ".");
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
  if (cfg.notice) await refreshStatus();  // e.g. the dark spectrum was discarded
  if (!state.live) await single();
}

// --- Dark spectrum ------------------------------------------------------------
function showDarkStatus(info) {
  const has = info.has_dark;
  $("subdark").disabled = !has;
  $("darkstatus").textContent = has
    ? `dark: ${info.dark_integration_time_ms} ms, ${info.dark_scans} scan${info.dark_scans > 1 ? "s" : ""}`
    : "no dark spectrum";
  $("darkstatus").className = has ? "chip ok" : "chip";
}
async function refreshStatus() {
  const { info, config } = await getJSON("/api/status");
  fillConfig(config);
  showDarkStatus(info);
  return info;
}
async function storeDark() {
  const d = await postJSON("/api/dark");
  await refreshStatus();
  notify(`Dark spectrum stored (${d.integration_time_ms} ms, ${d.scans} scan${d.scans > 1 ? "s" : ""}). ` +
         "Tick 'Subtract dark' to use it." +
         (d.scans < 10 ? " Tip: set 'Scans to average' to 10 or more first, for a less noisy dark." : ""));
}
async function clearDark() {
  await api("DELETE", "/api/dark");
  await refreshStatus();  // the server switched subtraction off
  notify("Dark spectrum cleared.");
  if (!state.live) await single();
}
// The checkbox acts at once (no Apply needed), for the live view and measurements.
async function toggleDark() {
  const want = $("subdark").checked;
  try {
    fillConfig(await postJSON("/api/config", { subtract_dark: want }));
    notify(want ? "Dark subtraction on (live view and measurements)." : "Dark subtraction off.");
    if (!state.live) await single();
  } catch (err) {
    $("subdark").checked = !want;
    notify(err.message, "error");
  }
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

// --- Example spectra (real data from the lab, see web/examples) ---------------
async function loadExamples() {
  try {
    state.examples = await getJSON("examples/index.json");
  } catch {
    state.examples = [];
  }
  for (const e of state.examples) {
    const o = document.createElement("option");
    o.value = e.id;
    o.textContent = `${e.title} (${e.kind})`;
    $("example").append(o);
  }
}
async function showExample(id) {
  const meta = (state.examples || []).find((e) => e.id === id);
  if (!meta) return;
  if (state.live) stopLive();
  const r = await fetch(`examples/${meta.file}`);
  if (!r.ok) throw new Error(`could not load example (${r.status})`);
  const rows = (await r.text()).split("\n").filter((l) => l && !l.startsWith("#")).slice(1)
    .map((l) => l.split(",").map(Number));
  const data = { wavelengths: rows.map((x) => x[1]), intensities: rows.map((x) => x[2]),
                 sem: rows.map((x) => x[3]) };
  state.source = "example";
  state.example = { meta, data };
  state.exampleFit = null;
  render(data, `Example · ${meta.title} · ${meta.recorded} · N = ${meta.num_scans} scans`);
  $("exinfo").textContent = `Example data, not from the connected spectrometer. ${meta.description}`;
  $("exinfo").hidden = false;
  if ($("cal").open) renderCalibration(true);
}
function leaveExample() {
  if (state.source !== "example") return;
  state.source = null;
  state.example = state.exampleFit = null;
  $("example").value = "";
  $("exinfo").hidden = true;
  if ($("cal").open) renderCalibration(true);
}

// --- Wavelength calibration: factory and custom side by side -------------------
let calInfo = null;
const polyval = (c, p) => c[0] + p * (c[1] + p * (c[2] + p * c[3]));
const fmtCoef = (x) => (x === 0 ? "0" : Math.abs(x) >= 0.01 && Math.abs(x) < 1e5 ? x.toPrecision(8) : x.toExponential(6));
const signed = (x) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(3);

function showCalibrationChip(info) {
  calInfo = info;
  state.calActive = info.active;
  const chip = $("calchip");
  if (info.active === "custom") {
    const rms = info.comparison.custom_rms_nm;
    chip.textContent = "λ calibration: custom" + (info.source === "fit"
      ? ` (fit${rms != null ? `, RMS ${rms.toFixed(2)} nm` : ""})` : " (coefficients)");
    chip.className = "chip custom";
  } else {
    chip.textContent = "λ calibration: factory";
    chip.className = "chip";
  }
}
async function loadCalibration() {
  showCalibrationChip(await getJSON("/api/calibration"));
}

// Device mode: factory vs custom calibration of this spectrometer.
// Example mode: the calibration the example was recorded with vs a practice fit.
function calModel() {
  if (state.source === "example" && state.example) {
    return { mode: "example", ref: state.example.meta.calibration,
             custom: state.exampleFit ? state.exampleFit.coefficients : null,
             comparison: state.exampleFit ? state.exampleFit.comparison : null,
             pixels: state.example.data.intensities.length };
  }
  return { mode: "device", ref: calInfo.factory_coefficients, custom: calInfo.custom_coefficients,
           comparison: calInfo.comparison, pixels: calInfo.pixels };
}

function renderCalibration(resetRows) {
  const m = calModel(), ex = m.mode === "example";
  const head = ex ? ["Recorded λ", "Recorded Δ", "Your fit λ", "Your fit Δ"]
                  : ["Factory λ", "Factory Δ", "Custom λ", "Custom Δ"];
  [...$("caltable").tHead.rows[0].cells].slice(2, 6).forEach((th, i) => { th.textContent = head[i]; });
  $("calsummary").textContent = ex
    ? `Practice with the example "${state.example.meta.title}": its wavelengths use the calibration it was ` +
      "recorded with (left). Fit the known lines to see how far that calibration is off. Nothing here " +
      "changes the calibration of your spectrometer."
    : calInfo.active === "custom"
      ? `In use: custom calibration (${calInfo.source === "fit"
          ? `fit of ${calInfo.comparison.lines.length} lines, order ${calInfo.order}` : "entered coefficients"}), ` +
        "saved for this spectrometer. The factory calibration stays in the spectrometer for comparison."
      : "In use: factory calibration (stored in the spectrometer).";
  $("calfit").textContent = ex ? "Fit lines (practice)" : "Fit lines and use";
  $("calapply").hidden = $("calreset").hidden = ex;

  const tb = $("calcoef");
  tb.replaceChildren();
  $("calcoef").closest("table").tHead.rows[0].cells[1].textContent = ex ? "Recorded with" : "Factory (in the spectrometer)";
  $("calcoef").closest("table").tHead.rows[0].cells[2].textContent = ex ? "Your fit" : "Custom";
  const custom = m.custom || m.ref;
  m.ref.forEach((f, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<th>c${i}</th><td>${fmtCoef(f)}</td><td></td>`;
    if (ex) {
      tr.cells[2].textContent = m.custom ? fmtCoef(m.custom[i]) : "–";
    } else {
      const inp = document.createElement("input");
      inp.type = "number"; inp.step = "any"; inp.id = `calc${i}`; inp.value = fmtCoef(custom[i]);
      tr.cells[2].append(inp);
    }
    tb.append(tr);
  });
  const c = m.comparison;
  $("caldiff").textContent = m.custom && c && c.max_difference_nm != null
    ? `Largest difference ${ex ? "fit − recorded" : "custom − factory"} over the detector: ` +
      `${signed(c.max_difference_nm)} nm (channel ${c.max_difference_pixel}).` : "";
  if (resetRows) {
    $("caltable").tBodies[0].replaceChildren();
    if (!ex) for (const l of calInfo.comparison.lines) addLineRow(l.pixel, l.wavelength_nm);
  }
  updateLineTable();
}
function addLineRow(pixel = "", wl = "") {
  const tr = document.createElement("tr");
  tr.innerHTML = '<td><input type="number" step="any" class="cpx" /></td>' +
    '<td><input type="number" step="any" class="cwl" list="lamplines" /></td>' +
    '<td></td><td></td><td></td><td></td><td><button type="button" title="Remove">×</button></td>';
  tr.querySelector(".cpx").value = pixel === "" ? "" : Number(pixel).toFixed(2);
  tr.querySelector(".cwl").value = wl;
  tr.querySelectorAll("input").forEach((el) => { el.oninput = updateLineTable; });
  tr.querySelector("button").onclick = () => { tr.remove(); updateLineTable(); };
  $("caltable").tBodies[0].append(tr);
  return tr;
}
function tableLines() {
  return [...$("caltable").tBodies[0].rows].map((tr) => ({
    tr, pixel: parseFloat(tr.querySelector(".cpx").value), wavelength_nm: parseFloat(tr.querySelector(".cwl").value),
  }));
}
function validLines() {
  return tableLines().filter((l) => Number.isFinite(l.pixel) && Number.isFinite(l.wavelength_nm))
    .map(({ pixel, wavelength_nm }) => ({ pixel, wavelength_nm }));
}
// Each line under both calibrations, recomputed while typing.
function updateLineTable() {
  if (!calInfo) return;
  const m = calModel(), res = { ref: [], custom: [] };
  for (const l of tableLines()) {
    const cells = l.tr.cells, okP = Number.isFinite(l.pixel), okW = Number.isFinite(l.wavelength_nm);
    const r = okP ? polyval(m.ref, l.pixel) : null;
    const c = okP && m.custom ? polyval(m.custom, l.pixel) : null;
    cells[2].textContent = r == null ? "" : r.toFixed(3);
    cells[3].textContent = r != null && okW ? signed(r - l.wavelength_nm) : "";
    cells[4].textContent = c == null ? "–" : c.toFixed(3);
    cells[5].textContent = c != null && okW ? signed(c - l.wavelength_nm) : "";
    if (r != null && okW) res.ref.push(r - l.wavelength_nm);
    if (c != null && okW) res.custom.push(c - l.wavelength_nm);
  }
  const rms = (a) => (a.length ? `${Math.sqrt(a.reduce((s, x) => s + x * x, 0) / a.length).toFixed(3)} nm` : "–");
  $("rmsf").textContent = rms(res.ref);
  $("rmsc").textContent = rms(res.custom);
}
// Centre of the peak next to the selected channel (sub-channel precision).
function selectedPeakPixel() {
  if (state.channel == null || !state.data) return null;
  const I = state.data.intensities, n = I.length;
  let best = state.channel;
  for (let i = Math.max(2, state.channel - 6); i <= Math.min(n - 1, state.channel + 6); i++) if (I[i] > I[best]) best = i;
  const lo = Math.max(0, best - 3), hi = Math.min(n - 1, best + 3);
  let base = Infinity, sw = 0, swx = 0;
  for (let i = lo; i <= hi; i++) base = Math.min(base, I[i]);
  for (let i = lo; i <= hi; i++) { sw += I[i] - base; swx += (I[i] - base) * i; }
  return sw > 0 ? swx / sw : best;
}
function openCalibration() {
  renderCalibration(true);
  $("calmsg").textContent = "";
  if (!$("cal").open) $("cal").show();  // not modal: the plot stays clickable for picking peaks
}
function addSelectedPeak() {
  const p = selectedPeakPixel();
  if (p == null) { $("calmsg").textContent = "First click on a peak in the spectrum."; return; }
  addLineRow(p, "").querySelector(".cwl").focus();
  updateLineTable();
}
async function fitCalibration() {
  const m = calModel();
  const order = $("calorder").value ? parseInt($("calorder").value, 10) : null;
  try {
    if (m.mode === "example") {
      state.exampleFit = await postJSON("/api/calibration/preview",
        { lines: validLines(), order, reference: m.ref, pixels: m.pixels });
      renderCalibration(false);
      $("calmsg").textContent = "Fitted (practice only: your spectrometer's calibration is unchanged).";
    } else {
      await afterCalibrationChange(await postJSON("/api/calibration", { lines: validLines(), order }),
                                   "Fitted, and in use for all wavelengths.");
    }
  } catch (err) {
    $("calmsg").textContent = err.message;
  }
}
async function applyCoefficients() {
  const coefficients = [0, 1, 2, 3].map((i) => parseFloat($(`calc${i}`).value));
  try {
    await afterCalibrationChange(await postJSON("/api/calibration", { coefficients, lines: validLines() }),
                                 "These coefficients are now in use.");
  } catch (err) {
    $("calmsg").textContent = err.message;
  }
}
async function resetCalibration() {
  await afterCalibrationChange(await api("DELETE", "/api/calibration"), "Back to the factory calibration.");
}
async function afterCalibrationChange(info, msg) {
  showCalibrationChip(info);
  renderCalibration(false);
  $("calmsg").textContent = msg + (info.save_error ? ` ${info.save_error}` : "");
  if (state.live) return;  // the next live frame brings the new wavelengths
  if (state.source === "measurement" && state.measurement) showMeasurement(await getJSON("/api/measurement"));
  else await single();
}

// --- Driver installation (Windows), from the connection dialog ------------------
async function installDriver() {
  const btn = $("diaginstall");
  btn.disabled = true;
  $("diagsummary").textContent = "Downloading and installing the driver. Windows asks for administrator approval…";
  try {
    const r = await postJSON("/api/driver/install");
    $("diagjson").textContent = r.log || "";
    if (!r.installed) {
      $("diagsummary").textContent = `Driver not installed: ${r.reason}`;
      return;
    }
    $("diagsummary").textContent = `Driver installed (${r.drivers.join(", ")})` +
      (r.reboot_required ? "; Windows asks for a restart." : ". Looking for the spectrometer…");
    if (!r.reboot_required) await retryHardware();
  } catch (err) {
    $("diagsummary").textContent = "Driver installation failed: " + err.message;
  } finally {
    btn.disabled = false;
  }
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
  showDarkStatus(info);
  await loadCalibration();
  loadExamples();
  const badge = $("badge");
  if (info.simulated) {
    badge.textContent = "SIMULATED" + (info.fallback_reason ? " · no spectrometer found ⓘ" : "");
    badge.className = "badge sim";
    badge.title = (info.fallback_reason ? info.fallback_reason + "\n\n" : "") + "Click for details and next steps.";
  } else {
    badge.textContent = info.model + (info.serial ? ` · ${info.serial}` : "");
    badge.title = "Click for connection details.";
  }
  if (info.has_measurement) showMeasurement(await getJSON("/api/measurement"));
  else await single();
  if (info.simulated && info.fallback_reason) openDiagnostics();  // say why right away
}

// --- Spectrometer connection diagnostics (dialog behind the badge) ----------
async function openDiagnostics() {
  const dlg = $("diag");
  $("diagsummary").textContent = "Checking the spectrometer connection…";
  $("diaghints").replaceChildren();
  $("diagjson").textContent = "";
  $("diagretry").hidden = true;
  if (!dlg.open) dlg.showModal();
  try {
    const r = await getJSON("/api/diagnostics");
    const s = r.spectrometer;
    $("diagsummary").textContent = !s.simulated
      ? `Connected: ${s.model}${s.serial ? " · " + s.serial : ""}`
      : s.forced_simulator ? "Simulator in use (started with --sim)."
      : `No spectrometer in use, showing simulated data. Reason: ${s.fallback_reason}`;
    for (const h of r.hints) {
      const li = document.createElement("li");
      li.textContent = h;
      $("diaghints").append(li);
    }
    $("diagjson").textContent = JSON.stringify(r, null, 2);
    $("diagretry").hidden = !s.simulated;
    $("diaginstall").hidden = !r.driver_install_available;
  } catch (err) {
    $("diagsummary").textContent = "Diagnostics failed: " + err.message;
  }
}
async function retryHardware() {
  if (state.live) stopLive();
  $("diagsummary").textContent = "Looking for the spectrometer…";
  try {
    const r = await postJSON("/api/reconnect");
    if (r.connected) { location.reload(); return; }
    await openDiagnostics();
  } catch (err) {
    $("diagsummary").textContent = "Retry failed: " + err.message;
  }
}
async function copyReport() {
  const pre = $("diagjson"), btn = $("diagcopy");
  try {
    await navigator.clipboard.writeText(pre.textContent);
    btn.textContent = "Copied";
  } catch {  // no clipboard access: select the text for Ctrl+C instead
    pre.parentElement.open = true;
    const range = document.createRange();
    range.selectNodeContents(pre);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    btn.textContent = "Press Ctrl+C";
  }
  setTimeout(() => { btn.textContent = "Copy report"; }, 2500);
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
$("subdark").onchange = toggleDark;
$("xmin").onchange = applyZoom;
$("xmax").onchange = applyZoom;
$("zoomreset").onclick = resetZoom;
$("example").onchange = (e) => {
  if (e.target.value) showExample(e.target.value).catch((err) => notify(err.message, "error"));
};
$("calchip").onclick = openCalibration;
$("caladdpeak").onclick = addSelectedPeak;
$("caladdrow").onclick = () => { addLineRow(); updateLineTable(); };
$("calfit").onclick = fitCalibration;
$("calapply").onclick = applyCoefficients;
$("calreset").onclick = guarded(resetCalibration);
$("calclose").onclick = () => $("cal").close();
$("diaginstall").onclick = installDriver;
$("badge").onclick = openDiagnostics;
$("diagretry").onclick = retryHardware;
$("diagcopy").onclick = copyReport;
$("diagclose").onclick = () => $("diag").close();
// Follow the size of the plot containers (window resize, a scrollbar appearing,
// zoom), not only window resizes; the containers do not grow with the canvas.
new ResizeObserver(() => {
  if (plot && $("plot").clientWidth) plot.setSize({ width: $("plot").clientWidth, height: MAIN_H });
  if (hplot && $("hplot").clientWidth) hplot.setSize({ width: $("hplot").clientWidth, height: HIST_H });
}).observe(document.querySelector("main"));

init().catch((err) => {
  $("badge").textContent = "server unreachable";
  $("readout").textContent = "Could not reach the local service: " + err.message;
});
