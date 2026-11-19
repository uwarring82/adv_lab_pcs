const {test} = require("node:test");
const assert = require("node:assert/strict");
const {toCSV, updatePlot, format} = require("../web/waveform.js");

const capture = {id: 75, captured_at: "2026-11-11T08:21:07.925263+00:00",
  info: {model: "DS1054Z", serial: "DS1ZA211102531", simulated: false},
  mode: "screen_preview", channel: 1,
  time_s: [-0.00006, -0.0000599], voltage_v: [4, 4.4]};

test("CSV samples are unquoted numbers and preserve the displayed values", () => {
  const lines = toCSV(capture).trimEnd().split("\r\n");
  assert.equal(lines[0], "# capture_id,75");
  assert.equal(lines[4], "# simulated,false");
  assert.equal(lines[6], "time_s,CH1_voltage_v");
  assert.equal(lines[7], "-0.00006,4");
  assert.equal(lines[8], "-0.0000599,4.4");
  assert.deepEqual(lines.slice(7).map(row => row.split(",").map(Number)),
    capture.time_s.map((t, i) => [t, capture.voltage_v[i]]));
});

test("CSV still escapes metadata containing separators, quotes or newlines", () => {
  const data = {...capture, info: {...capture.info, model: 'Model, "test"', serial: "line1\nline2"}};
  const csv = toCSV(data);
  assert.ok(csv.includes('# model,"Model, ""test"""\r\n'));
  assert.ok(csv.includes('# serial,"line1\nline2"\r\n'));
});

function plotWithRange(min, max) {
  return {data: [[0, 1, 2, 3], [0, 1, 0, -1]], scales: {x: {min, max}},
    setData(data) { this.data = data; },
    setScale(key, limits) { this.scales[key] = limits; this.rendered = this.data; }};
}
test("repeated capture requests a render even when the time axis stays unchanged", () => {
  const plot = plotWithRange(0, 3), data = [[0, 1, 2, 3], [5, -5, 5, -5]];
  updatePlot(plot, data);
  assert.equal(plot.rendered, data);
  assert.deepEqual(plot.scales.x, {min: 0, max: 3});
});
test("live updates retain an overlapping user zoom", () => {
  const plot = plotWithRange(1, 2), data = [[0, 1, 2, 3], [5, -5, 5, -5]];
  updatePlot(plot, data);
  assert.equal(plot.rendered, data);
  assert.deepEqual(plot.scales.x, {min: 1, max: 2});
});
test("unzoomed plots follow a changed instrument timebase", () => {
  const plot = plotWithRange(0, 3);
  updatePlot(plot, [[0, 2, 4, 6], [0, 1, 0, -1]]);
  assert.deepEqual(plot.scales.x, {min: 0, max: 6});
});
test("a zoom outside the new acquisition resets to show the available data", () => {
  const plot = plotWithRange(1, 2);
  updatePlot(plot, [[10, 11, 12, 13], [0, 1, 0, -1]]);
  assert.deepEqual(plot.scales.x, {min: 10, max: 13});
});

test("time and voltage use engineering units, so microsecond cursors never read 0 s", () => {
  assert.equal(format(-0.00006, "s"), "-60 µs");
  assert.equal(format(2.5e-9, "s"), "2.5 ns");
  assert.equal(format(0.0012, "s"), "1.2 ms");
  assert.equal(format(0, "s"), "0 s");
  assert.equal(format(4.4, "V"), "4.4 V");
  assert.equal(format(3e-11, "s"), "3.00e-11 s");
});

// Run the actual dashboard controller against a fake DOM/API. No browser or
// instrument is needed to check notices, button state and failure recovery.
async function dashboard() {
  const vm = require("node:vm"), fs = require("node:fs"), path = require("node:path");
  class Element {
    constructor() { this.value = ""; this.checked = false; this.disabled = false; this.options = []; this.dataset = {}; this.clientWidth = 600; }
    replaceChildren(...children) { this.options = children; }
  }
  const elements = new Map(), element = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const actions = ["run", "stop", "single", "autoscale"].map(action => {
    const button = new Element(); button.dataset.action = action; return button;
  });
  const state = {connected: false, error: null, failAction: null, failCapture: null};
  const info = {vendor: "HAMEG", model: "HMO3524", serial: "TEST", channels: 4, simulated: false,
    resource: "ftdi://0x0403:0xed72/1", unsupported_actions: ["autoscale"]};
  Object.entries({resource: info.resource, baud: "115200", flow: "none", termination: "LF",
    timeout: "5", settle: "0", channel: "1"}).forEach(([id, value]) => { element(id).value = value; });
  element("channel").options = [1, 2, 3, 4].map(value => ({value: String(value)}));
  const api = async (url, options = {}) => {
    const endpoint = url.replace("/api/", "");
    let data;
    if (endpoint === "status") data = {connected: state.connected, info: state.connected ? info : null, error: state.error};
    else if (endpoint === "connect") {
      state.connected = true; state.connection = JSON.parse(options.body);
      data = {...info, status_cleared: state.connection.clear_status === true};
    }
    else if (endpoint.startsWith("settings")) data = {timebase_s: 1e-5, scale_v: 5, coupling: "DC", acquisition_state: "RUN", channel: 1, enabled: true};
    else if (endpoint === "action" && state.failAction) {
      state.error = state.failAction;
      return {ok: false, status: 422, json: async () => ({detail: state.error})};
    } else if (endpoint === "capture" && state.failCapture) {
      state.connected = false; state.error = state.failCapture;
      return {ok: false, status: 503, json: async () => ({detail: state.error})};
    } else if (endpoint === "capture") {
      state.error = null;
      data = {...capture, info, points: 2, mean_v: 4.2, rms_v: 4.205, peak_to_peak_v: .4};
    } else data = {sent: true};
    return {ok: true, json: async () => data};
  };
  function Plot(options, data) {
    this.data = data;
    this.scales = {x: {min: data[0][0], max: data[0].at(-1)}};
    this.setData = updated => { this.data = updated; };
    this.setScale = (key, value) => { this.scales[key] = value; };
    this.setSize = this.destroy = () => {};
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../web/app.js"), "utf8"), {
    document: {getElementById: element, querySelectorAll: () => actions, createElement: () => new Element()},
    ScopeWaveform: require("../web/waveform.js"), fetch: api, uPlot: Plot,
    ResizeObserver: class { observe() {} }, setTimeout, clearTimeout,
  });
  await new Promise(setImmediate); // let the controller's initial status request complete
  return {element, actions, state};
}

test("connect requests status reset only when selected and reports the explicit clear", async () => {
  const ui = await dashboard();
  ui.element("clear-status").checked = true;
  await ui.element("connect").onclick();
  assert.equal(ui.state.connection.clear_status, true);
  assert.match(ui.element("notice").textContent, /cleared at your request \(\*CLS\)/);
  assert.equal(ui.element("notice").className, "");
  assert.equal(ui.element("capture").disabled, false);
  assert.equal(ui.actions.find(button => button.dataset.action === "autoscale").disabled, true);
});

test("Run errors stay visible and leave Capture usable for a subsequent success", async () => {
  const ui = await dashboard();
  await ui.element("connect").onclick();
  assert.equal(ui.state.connection.clear_status, false);
  ui.state.failAction = 'Instrument reported -101,"Invalid character" after run';
  await ui.actions.find(button => button.dataset.action === "run").onclick();
  assert.match(ui.element("notice").textContent, /after run/);
  assert.equal(ui.element("notice").className, "error");
  assert.equal(ui.element("capture").disabled, false);
  assert.equal(ui.element("controls").disabled, false);
  await ui.element("capture").onclick();
  assert.match(ui.element("notice").textContent, /^Screen captured/);
  assert.equal(ui.element("points").textContent, 2);
  assert.equal(ui.element("export").disabled, false);
});

test("capture transport failure disables collection and retains the previous export", async () => {
  const ui = await dashboard();
  await ui.element("connect").onclick();
  await ui.element("capture").onclick();
  ui.state.failCapture = "No usable reply to :SYST:ERR? from HMO3524";
  await ui.element("capture").onclick();
  assert.match(ui.element("notice").textContent, /:SYST:ERR/);
  assert.equal(ui.element("capture").disabled, true);
  assert.equal(ui.element("controls").disabled, true);
  assert.equal(ui.element("export").disabled, false);
});
