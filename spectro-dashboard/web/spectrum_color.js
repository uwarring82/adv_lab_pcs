"use strict";
// Wavelength -> sRGB via the CIE 1931 2-degree colour-matching functions.
// Ported from wavelength_to_rgb_cie in the Freiburg lab's earlier (unpublished)
// Python control code, so the colour strip matches the figures students know;
// the output agrees with that code to floating-point precision.
(function (root) {
  const WL0 = 380, STEP = 5;  // table: 380-780 nm every 5 nm
  const XBAR = [0.0014,0.0022,0.0042,0.0076,0.0143,0.0232,0.0435,0.0776,0.1344,0.2148,0.2839,0.3285,0.3483,0.3481,0.3362,0.3187,0.2908,0.2511,0.1954,0.1421,0.0956,0.058,0.032,0.0147,0.0049,0.0024,0.0093,0.0291,0.0633,0.1096,0.1655,0.2257,0.2904,0.3597,0.4334,0.5121,0.5945,0.6784,0.7621,0.8425,0.9163,0.9786,1.0263,1.0567,1.0622,1.0456,1.0026,0.9384,0.8544,0.7514,0.6424,0.5419,0.4479,0.3608,0.2835,0.2187,0.1649,0.1212,0.0874,0.0636,0.0468,0.0329,0.0227,0.0158,0.0114,0.0081,0.0058,0.0041,0.0029,0.002,0.0014,0.001,0.0007,0.0005,0.0003,0.0002,0.0002,0.0001,0.0001,0,0];
  const YBAR = [0,0.0001,0.0001,0.0002,0.0004,0.0006,0.0012,0.0022,0.004,0.0073,0.0116,0.0168,0.023,0.0298,0.038,0.048,0.06,0.0739,0.091,0.1126,0.139,0.1693,0.208,0.2586,0.323,0.4073,0.503,0.6082,0.71,0.7932,0.862,0.9149,0.954,0.9803,0.9949,1,0.995,0.9786,0.952,0.9154,0.87,0.8163,0.757,0.6949,0.631,0.5668,0.503,0.4412,0.381,0.321,0.265,0.217,0.175,0.1382,0.107,0.0816,0.061,0.0446,0.032,0.0232,0.017,0.0119,0.0082,0.0057,0.0041,0.0029,0.0021,0.0015,0.001,0.0007,0.0005,0.0004,0.0002,0.0002,0.0001,0.0001,0.0001,0,0,0,0];
  const ZBAR = [0.0065,0.0105,0.0201,0.0362,0.0679,0.1102,0.2074,0.3713,0.6456,1.0391,1.3856,1.6229,1.7471,1.7826,1.7721,1.7441,1.6692,1.5281,1.2876,1.0419,0.813,0.6162,0.4652,0.3533,0.272,0.2123,0.1582,0.1117,0.0782,0.0573,0.0422,0.0298,0.0203,0.0134,0.0087,0.0057,0.0039,0.0027,0.0021,0.0018,0.0017,0.0014,0.0011,0.001,0.0008,0.0006,0.0003,0.0002,0.0002,0.0001,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0];
  // XYZ -> linear sRGB (D65)
  const M = [[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]];

  // Linear interpolation, 0 outside the table (like interp1d(..., fill_value=0)).
  function interp(table, wl) {
    const f = (wl - WL0) / STEP;
    if (!(f >= 0 && f <= table.length - 1)) return 0;
    const i = Math.floor(f), t = f - i;
    return i + 1 < table.length ? table[i] * (1 - t) + table[i + 1] * t : table[i];
  }
  const encode = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);

  /** [r, g, b] in 0..1 (gamma-encoded sRGB) for a wavelength in nm; black outside 380-780 nm. */
  function wavelengthToRGB(wl) {
    const X = interp(XBAR, wl), Y = interp(YBAR, wl), Z = interp(ZBAR, wl);
    return M.map(([a, b, c]) => Math.min(Math.max(encode(Math.max(a * X + b * Y + c * Z, 0)), 0), 1));
  }

  const api = { wavelengthToRGB, VISIBLE: [WL0, WL0 + STEP * (XBAR.length - 1)] };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SpectrumColor = api;
})(this);
