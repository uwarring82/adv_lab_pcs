"use strict";
// Shared by the dashboard and the browser/Node regression tests.
const ScopeWaveform = (() => {
  function updatePlot(plot, data) {
    const previous = plot.data[0], next = data[0];
    const {min, max} = plot.scales.x;
    const tolerance = Math.abs(previous[previous.length - 1] - previous[0]) * 1e-9;
    const zoomed = Math.abs(min - previous[0]) > tolerance ||
                   Math.abs(max - previous[previous.length - 1]) > tolerance;
    const overlaps = max > next[0] && min < next[next.length - 1];
    plot.setData(data, false);
    // setData(..., false) alone does not schedule a draw in uPlot 1.6.31.
    // Setting x also rebuilds paths and recalculates y from the new samples.
    plot.setScale("x", zoomed && overlaps ? {min, max} : {min: next[0], max: next[next.length - 1]});
  }

  function csvField(value) {
    const text = String(value);
    return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  }

  function toCSV(data) {
    const rows = [["# capture_id", data.id], ["# captured_at", data.captured_at],
      ["# model", data.info.model], ["# serial", data.info.serial],
      ["# simulated", data.info.simulated], ["# mode", data.mode],
      ["time_s", `CH${data.channel}_voltage_v`],
      ...data.time_s.map((t, i) => [t, data.voltage_v[i]])];
    return rows.map(row => row.map(csvField).join(",")).join("\r\n") + "\r\n";
  }

  // Engineering-unit text for axes and the cursor readout: 60 µs, not "0 s".
  function format(value, unit) {
    if (value === 0) return `0 ${unit}`;
    for (const [scale, prefix] of [[1e3,"k"],[1,""],[1e-3,"m"],[1e-6,"µ"],[1e-9,"n"]]) {
      if (Math.abs(value) >= scale) return `${Number((value / scale).toPrecision(4))} ${prefix}${unit}`;
    }
    return `${value.toExponential(2)} ${unit}`;
  }

  return {updatePlot, toCSV, format};
})();
if (typeof module !== "undefined") module.exports = ScopeWaveform;
