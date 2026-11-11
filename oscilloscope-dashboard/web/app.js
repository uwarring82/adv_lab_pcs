"use strict";
const $ = id => document.getElementById(id);
let connected = false, busy = false, live = false, last = null, plot = null;
let confirmed = null, timer = null;
const colors = ["#1f77b4", "#d27600", "#2a8b44", "#9467bd"];

function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
}
async function api(path, body) {
  const response = await fetch(`/api/${path}`, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(d => `${d.loc.join(".")}: ${d.msg}`).join("; ") : data.detail;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return data;
}
function controls() {
  $("controls").disabled = !connected || busy || live;
  ["connect", "simulate", "discover"].forEach(id => { $(id).disabled = busy || live; });
  $("disconnect").disabled = !connected || busy || live;
  $("capture").disabled = !connected || busy || live;
  $("live").disabled = !connected || (busy && !live);
  $("live").textContent = live ? "Pause live preview" : "Start live preview";
  $("export").disabled = !last;
}
function pause() { live = false; clearTimeout(timer); controls(); }
function clearCapture() {
  last = null;
  if (plot) { plot.destroy(); plot = null; }
  ["vpp", "rms", "mean", "points"].forEach(id => { $(id).textContent = "—"; });
  $("empty").hidden = false;
  $("preview-state").textContent = "No capture";
  $("capture-info").textContent = "Drag across the plot to zoom. CSV exports the exact displayed capture in seconds and volts.";
}
async function status() {
  const data = await api("status");
  connected = data.connected;
  $("badge").textContent = connected ? (data.info.simulated ? "SIMULATED DATA" : "HARDWARE") : "Disconnected";
  $("badge").className = connected ? (data.info.simulated ? "sim" : "hardware") : "";
  $("device").textContent = connected ? `${data.info.vendor} ${data.info.model} · ${data.info.serial} · ${data.info.resource || "Synthetic 1 kHz signal"}` : (data.error || "Select a resource to identify the instrument, or try synthetic data.");
  if (connected) {
    const count = data.info.channels;
    for (const option of $("channel").options) option.disabled = Number(option.value) > count;
    if (Number($("channel").value) > count) $("channel").value = "1";
  } else { pause(); }
  controls();
}
async function readSettings() {
  confirmed = await api(`settings?channel=${$("channel").value}`);
  $("timebase").value = confirmed.timebase_s;
  $("scale").value = confirmed.scale_v;
  $("coupling").value = confirmed.coupling;
  $("acquisition").textContent = `Acquisition: ${confirmed.acquisition_state} · CH${confirmed.channel} ${confirmed.enabled ? "enabled" : "disabled"}`;
}
async function task(fn) {
  if (busy) return;
  pause(); busy = true; controls(); notice("Working…");
  try { await fn(); }
  catch (error) {
    notice(error.message, true);
    try { await status(); } catch (_) { connected = false; }
  } finally { busy = false; controls(); }
}
function format(value, unit) {
  if (value === 0) return `0 ${unit}`;
  for (const [scale, prefix] of [[1e3,"k"],[1,""],[1e-3,"m"],[1e-6,"µ"],[1e-9,"n"]]) {
    if (Math.abs(value) >= scale) return `${Number((value / scale).toPrecision(4))} ${prefix}${unit}`;
  }
  return `${value.toExponential(2)} ${unit}`;
}
function draw(data) {
  const changedChannel = !last || last.channel !== data.channel;
  last = data;
  $("empty").hidden = true;
  if (changedChannel && plot) { plot.destroy(); plot = null; }
  if (!plot) {
    plot = new uPlot({width: $("plot").clientWidth, height: 330,
      scales: {x: {time: false}},
      axes: [{label: "Time", values: (u, ticks) => ticks.map(t => format(t, "s"))},
             {label: "Voltage", size: 75, values: (u, ticks) => ticks.map(v => format(v, "V"))}],
      series: [{label: "Time (s)"}, {label: `CH${data.channel} (V)`, stroke: colors[data.channel - 1], width: 1.5}],
      cursor: {drag: {x: true, y: false}}, legend: {show: true}
    }, [data.time_s, data.voltage_v], $("plot"));
  } else {
    ScopeWaveform.updatePlot(plot, [data.time_s, data.voltage_v]);
  }
  $("vpp").textContent = format(data.peak_to_peak_v, "V");
  $("rms").textContent = format(data.rms_v, "V");
  $("mean").textContent = format(data.mean_v, "V");
  $("points").textContent = data.points;
  $("preview-state").textContent = `CH${data.channel} · ${data.info.simulated ? "SIMULATED" : "Screen preview"}`;
  $("capture-info").textContent = `Capture ${data.id} · ${new Date(data.captured_at).toLocaleTimeString()} · ${data.info.model} · ${data.info.serial}. CSV uses seconds and volts.`;
  controls();
}
async function capture() { draw(await api("capture", {channel: Number($("channel").value)})); }
async function tick() {
  if (!live || busy) return;
  busy = true; controls();
  try { await capture(); notice("Live screen snapshots; acquisitions between reads are not recorded. Pause to change controls."); }
  catch (error) { pause(); notice(error.message, true); try { await status(); } catch (_) { connected = false; } }
  finally { busy = false; controls(); if (live) timer = setTimeout(tick, 750); }
}
$("discover").onclick = () => task(async () => {
  const data = await api("resources");
  $("resources").replaceChildren(...data.resources.map(r => { const o = document.createElement("option"); o.value = r; return o; }));
  if (!$("resource").value && data.resources.length) $("resource").value = data.resources[0];
  notice(data.resources.length ? `Found ${data.resources.length} resources. Select the scope, then connect.` : "No USB or serial resources found. Check VISA drivers and cables, or enter the resource manually.");
});
async function connect(simulated) {
  clearCapture();
  await api(simulated ? "simulator" : "connect", simulated ? {} : {
    resource: $("resource").value.trim(), baud_rate: Number($("baud").value),
    flow_control: $("flow").value, termination: $("termination").value,
    timeout_ms: Math.round(Number($("timeout").value) * 1000)
  });
  await status(); await readSettings();
  notice(simulated ? "Simulator connected. All waveforms are synthetic." : "Connected. Compare the first capture with the instrument display; see model coverage below.");
}
$("connect").onclick = () => task(() => connect(false));
$("simulate").onclick = () => task(() => connect(true));
$("disconnect").onclick = () => task(async () => { await api("disconnect", {}); clearCapture(); await status(); notice("Disconnected."); });
$("channel").onchange = () => task(async () => { clearCapture(); await readSettings(); notice("Channel selected. Capture to display it."); });
$("refresh").onclick = () => task(async () => { await readSettings(); notice("Settings read from the instrument."); });
$("settings").onsubmit = event => {
  event.preventDefault();
  task(async () => {
    const values = {timebase_s: Number($("timebase").value), scale_v: Number($("scale").value), coupling: $("coupling").value};
    const diff = Object.fromEntries(Object.entries(values).filter(([key, value]) => value !== confirmed?.[key]));
    if (!Object.keys(diff).length) { notice("No settings changed."); return; }
    await api("settings", {channel: Number($("channel").value), ...diff});
    await readSettings(); clearCapture(); notice("Settings applied and read back from the instrument.");
  });
};
document.querySelectorAll("[data-action]").forEach(button => {
  button.onclick = () => task(async () => {
    await api("action", {action: button.dataset.action});
    await readSettings();
    if (button.dataset.action === "autoscale") clearCapture();
    notice(button.dataset.action === "single" ? "Single acquisition armed. Wait for the trigger before capturing." : "Command sent. Acquisition state refreshed.");
  });
});
$("capture").onclick = () => task(async () => { await capture(); notice("Screen captured. Export saves these exact samples."); });
$("live").onclick = () => { if (live) { pause(); notice("Preview paused. The instrument’s acquisition state is unchanged."); } else { live = true; tick(); } };
$("reset").onclick = () => { if (plot && last) plot.setData([last.time_s, last.voltage_v]); };
$("export").onclick = () => {
  if (!last) return;
  // Save the browser's displayed snapshot even if another client has acquired again.
  const d = last;
  const blob = new Blob([ScopeWaveform.toCSV(d)], {type: "text/csv"});
  const url = URL.createObjectURL(blob), link = document.createElement("a");
  link.href = url; link.download = `oscilloscope-${d.info.simulated ? "sim-" : ""}${d.id}.csv`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
new ResizeObserver(() => { if (plot) plot.setSize({width: $("plot").clientWidth, height: 330}); }).observe($("plot"));
task(async () => { await status(); if (connected) await readSettings(); notice(connected ? "Ready to capture." : "Connect an oscilloscope or start the simulator."); });
