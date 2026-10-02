# HTTP API reference

Everything the dashboard does is available over plain HTTP, so students can script
their own measurements in Python or any other language. While the app is running, an
interactive version of this reference (try requests in the browser) is at
**<http://127.0.0.1:8777/docs>**.

## Conventions

- Base URL: `http://127.0.0.1:8777` (the port can be changed with `--port`).
- JSON in and out. Intensities are in detector **counts** (16-bit ADC, saturation at
  2¹⁶ = 65536).
- In every spectrum, **list index = channel number** (pixel). `wavelengths[i]` is the
  calibrated wavelength of channel `i` in nm.
- `sem` is the standard error of the mean: `std(ddof=1) / √N` over the N scans that
  were averaged (0 when N = 1).

## Quick start (Python)

```python
import requests

base = "http://127.0.0.1:8777"

# settings (send only what you want to change)
requests.post(f"{base}/api/config", json={"integration_time_ms": 120, "scans_to_average": 5}).raise_for_status()

# one live spectrum
s = requests.get(f"{base}/api/spectrum").json()
wl, counts, sem = s["wavelengths"], s["intensities"], s["sem"]

# statistical measurement: 200 raw scans -> mean and SEM per channel
m = requests.post(f"{base}/api/measurement", json={"num_scans": 200}).json()

# intensity histogram of one channel over those 200 scans
h = requests.get(f"{base}/api/measurement/histogram", params={"channel": 616}).json()
```

CSV straight into pandas:

```python
import pandas as pd
df = pd.read_csv("http://127.0.0.1:8777/api/measurement.csv", comment="#")
```

A complete example, including a plot in the lab-notebook style, is
[`spectro-dashboard/examples/student_client.py`](../spectro-dashboard/examples/student_client.py).

## Endpoints

### Information

| Method & path | Returns |
|---|---|
| `GET /api/health` | `{"status": "ok"}` |
| `GET /api/status` | `{"info": {...}, "config": {...}}`: device model, serial, number of pixels, wavelength and integration-time range, `simulated` (and `fallback_reason` if no hardware was found), dark-spectrum and measurement state, and the `limits` below |
| `GET /api/diagnostics` | Why no spectrometer is used, with next steps in `hints`: the seabreeze backend that loads and the devices it sees, and on Windows every Ocean Optics USB device (vendor ID 2457) with its driver. Takes a few seconds on Windows. |
| `POST /api/reconnect` | Looks for the spectrometer again (e.g. after closing OceanView). Returns `{"connected": true, "model", "serial"}` or `{"connected": false, "reason"}`. Switching from the simulator to hardware resets settings, dark spectrum and measurement. |
| `POST /api/driver/install` | Windows only: downloads Ocean Optics' Microsoft-signed WinUSB driver (a fixed version, checked by SHA-256) and installs it for the connected Ocean Optics devices that have no working driver. Windows asks for administrator approval. Returns `{"installed", "reboot_required", "drivers", "hardware_ids", "log", "reason"}`; then call `/api/reconnect`. |

### Settings

| Method & path | Body / returns |
|---|---|
| `GET /api/config` | `{"integration_time_ms", "scans_to_average", "boxcar_width", "subtract_dark"}` |
| `POST /api/config` | Any subset of those fields. Returns the new config plus `notice` (a message, or `null`). Invalid values reject the **whole** request and change nothing. |
| `POST /api/dark` | Stores the mean and SEM of `scans_to_average` raw scans as the dark spectrum for the current integration time. Returns `{"has_dark": true, "integration_time_ms", "scans"}`. |
| `DELETE /api/dark` | Discards the dark spectrum and switches subtraction off. |

Settings fields:

| Field | Meaning |
|---|---|
| `integration_time_ms` | Exposure time. Changing it **discards the dark spectrum** and switches `subtract_dark` off; the response's `notice` says so. |
| `scans_to_average` | Live view: number of scans averaged into each spectrum (mean ± SEM). |
| `boxcar_width` | Live view: smoothing half-width in pixels (0 = off). The average near the edges uses the pixels that exist, and the SEM is propagated. |
| `subtract_dark` | Live view **and measurements**: subtract the dark spectrum; its SEM is added in quadrature. Can only be switched on while a dark spectrum taken at the current integration time exists. |

*Scans to average* and *boxcar* apply to the live view only; measurements are never
smoothed. Histograms always use raw counts.

### Live data

| Method & path | Returns |
|---|---|
| `GET /api/spectrum` | One live spectrum: `{"timestamp", "model", "wavelengths", "intensities", "sem", "config"}` |
| `GET /api/spectrum.csv` | The same as CSV (see [CSV format](#csv-format)) |
| `WS /ws/stream` | A continuous stream of the same JSON objects, one per acquisition, paced by integration time × scans to average |

### Statistical measurement

| Method & path | Body / returns |
|---|---|
| `POST /api/measurement` | Body `{"num_scans": N}` (default 200). Takes N scans and returns `{"id", "timestamp", "model", "num_scans", "config", "calibration", "wavelengths", "mean", "sem", "dark_subtracted"}`. With `subtract_dark` on, `mean`/`sem` are dark-corrected and the response adds `raw_mean`, `raw_sem`, `dark`, `dark_sem`, `dark_scans`. The call blocks until the measurement is done (N × integration time). |
| `GET /api/measurement` | The latest measurement (same format), or `404` if there is none yet |
| `GET /api/measurement/progress` | `{"running", "done", "total"}`; poll it from a second client while a measurement runs |
| `GET /api/measurement/histogram?channel=C&bins=B` | Histogram of channel `C` over the scans of the latest measurement: `{"measurement_id", "channel", "wavelength_nm", "num_scans", "counts", "bin_edges", "bins_capped", "mean", "std", "sem"}`. `bins` is a number (1–1000) or a numpy rule: `auto` (default), `fd`, `doane`, `scott`, `stone`, `rice`, `sturges`, `sqrt`. `len(bin_edges) == len(counts) + 1`. |
| `GET /api/measurement.csv` | The latest measurement as CSV |

`id` increases with every completed measurement; the histogram's `measurement_id`
tells you which measurement it belongs to.

Only **one measurement runs at a time**. While it runs, other requests that need the
spectrometer (live spectra, settings, dark) return `409` instead of waiting; the live
WebSocket stream pauses and resumes afterwards.

### Wavelength calibration

Wavelengths follow λ(p) = c0 + c1·p + c2·p² + c3·p³ (p = channel), either the factory
polynomial stored in the spectrometer or a custom one, saved per device (model and
serial) on the PC.

| Method & path | Body / returns |
|---|---|
| `GET /api/calibration` | `{"active": "factory" \| "custom", "source", "order", "pixels", "factory_coefficients", "custom_coefficients", "comparison", "saved_in", "save_error"}`. `comparison` lists every reference line with its position under both calibrations (`factory_nm`, `factory_residual_nm`, `custom_nm`, `custom_residual_nm`), the RMS of both and their largest difference across the detector. |
| `POST /api/calibration` | Either `{"lines": [{"pixel", "wavelength_nm"}, ...], "order": 1–3}` to fit (order defaults to number of lines − 1, at most 3), or `{"coefficients": [c0, c1, c2, c3]}` (lines optional, kept for comparison). The result is used for all wavelengths from then on. Returns the same as `GET`. |
| `DELETE /api/calibration` | Back to the factory calibration. |
| `POST /api/calibration/preview` | `{"lines", "order", "reference": [c0..c3], "pixels"}`: fits without using the result, and compares it with `reference`, e.g. the calibration an example spectrum was recorded with. |

### Example spectra

Static files served with the dashboard: `GET /examples/index.json` lists them (title,
description, recording date, number of scans, the calibration they were recorded with),
`GET /examples/<file>.csv` returns one (`channel, wavelength_nm, mean_counts, sem_counts,
std_counts`). See `spectro-dashboard/web/examples/README.md`.

## CSV format

Comment lines start with `#` and record the context; then a header and one row per
channel:

```text
# model=USB2000PLUS
# timestamp=1790796136.30
# num_scans=200
# config={'integration_time_ms': 100.0, 'scans_to_average': 1, 'boxcar_width': 0, 'subtract_dark': False}
# dark_subtracted=False
# wavelength_calibration=factory: lambda(p) = c0 + c1 p + c2 p^2 + c3 p^3, c = [339.4, 0.3846, -1.71e-05, 2.1e-10]
channel,wavelength_nm,mean_counts,sem_counts
0,339.4000,635.0600,3.2021
...
```

With dark subtraction the measurement CSV adds the columns `raw_mean_counts,
raw_sem_counts, dark_counts, dark_sem_counts`. The live CSV (`/api/spectrum.csv`) has
the columns `channel, wavelength_nm, intensity_counts, sem_counts` and no `num_scans`
or `dark_subtracted` line.

## Limits

Requests are checked **before** the spectrometer is touched.

| Limit | Value |
|---|---|
| Integration time | the device's range (`integration_time_min_ms` … `integration_time_max_ms` in `/api/status`) |
| Live: scans to average | 1–1000; when averaging (2 or more scans), scans × integration time ≤ 30 s. A single exposure may use the full integration range. |
| Live: boxcar half-width | 0 … (pixels − 1) / 2, i.e. 1023 for a 2048-pixel detector |
| Measurement | 2–5000 scans, and scans × integration time ≤ 30 min |
| Histogram bins | 1–1000. Rule-based binning that would need more bins is capped at 1000 and flagged with `bins_capped: true`. |

`GET /api/status` reports the current values under `info.limits`.

## Errors

| Status | Meaning | Body |
|---|---|---|
| `404` | No measurement yet (measurement, histogram and measurement-CSV endpoints) | `{"detail": "..."}` |
| `409` | A measurement is running; try again when it has finished | `{"detail": "..."}` |
| `422` | Invalid request: out-of-range value, unknown bin rule, dark subtraction without a matching dark spectrum, ... Nothing was changed. | `{"detail": "readable message"}`, or for malformed JSON/types a list of `{"loc", "msg"}` entries |

In Python, `response.raise_for_status()` turns these into exceptions; the message is
in `response.json()["detail"]`.

## Stability

The API is versioned together with the application (`/docs` shows the version). Until
1.0, fields may still be added; existing fields are only changed with a note in the
[changelog](../CHANGELOG.md).
