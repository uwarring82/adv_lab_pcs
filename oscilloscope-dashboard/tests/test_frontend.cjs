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
