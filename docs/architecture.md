# Architecture

This document explains how the pieces fit together and why they are built the way
they are. It is meant for developers who want to change or extend the project.

## Overview

```
 Browser (dashboard)          Student script (Python, ...)
        │  HTTP + WebSocket          │  HTTP
        └──────────────┬─────────────┘
                       ▼
        FastAPI app  (spectro/app.py)          127.0.0.1:8777
          REST /api/…   WebSocket /ws/stream   static web/   /docs
                       │
                       ▼
        AcquisitionManager  (spectro/acquisition.py)
          validation · live processing · measurements · histograms · dark
                       │  one lock around every device access
                       ▼
        SpectrometerBackend  (spectro/backend/)
          SeabreezeSpectrometer (python-seabreeze)  |  SimulatedSpectrometer
```

The same process serves the dashboard and the student API, so there is exactly one
owner of the USB device. For deployment, `run.py` (start the server, open the
browser) is frozen into a single `.exe` with PyInstaller.

## Backends

`SpectrometerBackend` (`spectro/backend/base.py`) is the only interface the rest of the
code sees: `wavelengths()`, `intensities()`, `set_integration_time_ms()`,
`integration_time_limits_ms`, `close()`, plus `model` and `serial`.

- `SeabreezeSpectrometer` wraps python-seabreeze and reads **raw counts**
  (`correct_dark_counts=False, correct_nonlinearity=False`), as the lab's analysis
  notebooks did. seabreeze is imported lazily, so the rest of the app runs on machines
  without it.
- `SimulatedSpectrometer` produces a USB2000+-like spectrum (2048 pixels, 340–1025 nm,
  lamp baseline plus emission lines, shot and read noise, integer counts clipped to 16
  bit) and sleeps for the integration time like real hardware. `realtime=False`
  disables the sleep for tests.
- `open_backend()` tries the hardware and falls back to the simulator, recording the
  reason; the dashboard shows it in the **SIMULATED** badge.

## Acquisition model

### Locks

- `_lock` guards the device. Every hardware access (scans, integration time, close)
  holds it.
- `_measure_lock` allows only **one measurement at a time**. A second measurement
  request, and any other device request made while a measurement runs, raises `Busy`
  (HTTP 409) instead of waiting. A long measurement therefore cannot make other
  requests hang for up to half an hour.

### Live view

`acquire()` averages `scans_to_average` scans with **Welford's algorithm**: memory stays
at one spectrum regardless of the number of scans. It returns the mean and the standard
error of the mean (`std(ddof=1)/√N`), then optionally subtracts the dark spectrum and
applies boxcar smoothing.

The boxcar average divides by the number of pixels actually inside the window, so a
flat spectrum stays flat at the edges, and it propagates the SEM for uncorrelated
pixels: `SEM_smoothed = √(Σ SEM_i²) / k` for a window of `k` pixels.

### Measurements

`measure(N)` records N raw scans into an `(N, pixels)` float32 block, computes mean and
SEM, and **publishes the result in one step** while still holding the device lock.
The progress indicator switches to "not running" only afterwards, so a client that sees
`running: false` always finds the new result. Each result carries an increasing `id`.
The block is kept for `histogram(channel, bins)`.

Measurements are never smoothed. With `subtract_dark` on, the mean is corrected by the
dark spectrum, `SEM = √(SEM_raw² + SEM_dark²)` (signal and dark are independent
measurements), and the raw mean/SEM and the dark spectrum are returned alongside. The
scan block stays raw, so histograms always show the detector's own statistics.

### Dark spectrum

`store_dark()` keeps the mean **and SEM** of `scans_to_average` scans (Welford) together
with the integration time; the live view and measurements subtract it with the SEMs
added in quadrature.

### Wavelength calibration

`spectro/calibration.py`. Ocean Optics store λ(p) = c0 + c1·p + c2·p² + c3·p³ in the
spectrometer; the factory coefficients are recovered from the device's wavelengths with
a cubic fit (exact for that form; terms below 10⁻⁶ nm across the detector are reported
as 0). A custom calibration (entered coefficients, or a least-squares fit to reference
lines of order 1–3) must give increasing wavelengths across the detector. It replaces
`_wl`, so every spectrum, measurement, histogram and CSV uses it, and is saved per device
key `model:serial` in a JSON file (`%APPDATA%\SpectrometerDashboard\calibrations.json`,
on other systems `~/.config/spectrometer-dashboard/`). A saved calibration that does
not fit the device is ignored. `compare()` produces the side-by-side view for students:
each reference line under both polynomials, both RMS values, and the largest difference
across the detector. `/api/calibration/preview` fits without applying, for practising
on example spectra recorded with another calibration.

### Configuration

`AcquisitionConfig` is a frozen dataclass that is **replaced, never mutated**.
`update_config()` validates the complete new configuration first and changes nothing
if any value is invalid (`AcquisitionError`, HTTP 422).

The dark spectrum is stored together with the integration time it was taken at. The
invariant is: *`subtract_dark` is true only while a dark spectrum for the current
integration time exists.* Changing the integration time therefore discards the dark
spectrum and switches subtraction off, with a `notice` in the response.

### Limits

All limits are constants at the top of `acquisition.py` and exposed through
`GET /api/status`. They protect the instrument PC, not the user's freedom:

| Limit | Protects against |
|---|---|
| ≤ 1000 live scans, and ≤ 30 s when averaging | a live frame that never finishes |
| a single exposure may use the device's full range | (not a limit: long exposures must stay possible for measurements) |
| ≤ 5000 measurement scans, ≤ 30 min | memory (block ≈ 40 MB) and blocking the instrument |
| boxcar half-width ≤ (pixels − 1)/2 | output length changes in `np.convolve` |
| ≤ 1000 histogram bins; `fd`/`auto` estimated before numpy allocates | a few outlier scans making numpy allocate millions of bins |

## HTTP layer

`spectro/app.py` maps `AcquisitionError` to 422 and `Busy` to 409 with a readable
`detail`; pydantic models (`spectro/models.py`) validate request shapes and generate
the `/docs` schema. Blocking device calls run in worker threads (sync endpoints, and
`asyncio.to_thread` in the WebSocket loop), so the event loop stays responsive. The
WebSocket loop waits out a running measurement instead of closing. CSV rows are zipped
with `strict=True`, so a length mismatch fails loudly instead of truncating data.
Everything outside `/api/` is served with `Cache-Control: no-cache` (browsers
revalidate with cheap 304s), so an updated executable never runs with a cached page
from the previous version.

## Web frontend

Plain HTML, CSS and JavaScript in `web/`, with no build step, so students can read it
and PyInstaller can bundle it as-is. [uPlot](https://github.com/leeoniya/uPlot) is
vendored in `web/lib/`, so the page works offline.

- **Figures** follow the lab's matplotlib notebooks: tab:blue mean, grey ±SEM band,
  red saturation line at 2¹⁶, y fixed to 0…2¹⁶ unless autoscaled, channels 0–1 hidden,
  histogram bars with black edges. The saturation line is drawn in a draw hook rather
  than as a data series, so autoscaling fits the data rather than the line.
- **Zoom** is stored and re-applied on every live frame. Autoscale uses uPlot's
  visible-window minimum and maximum.
- **Colour strip** (`web/spectrum_color.js`): for each screen column, the nearest
  channel's wavelength is converted to sRGB with the CIE 1931 colour-matching
  functions and scaled by `(I/I_max)^0.8`, with `I_max` over the visible channels in
  the current window. The conversion is a port of the lab's earlier Python code, and
  its output matches that code to floating-point precision.
- **Settings** are sent as a *diff* against the last configuration the server
  confirmed. Sending the whole form would re-send a stale `subtract_dark: true` along
  with a new integration time and get the whole update rejected.
- Server errors (`detail`) and notices are shown in the toolbar.

## Packaging

`packaging/build_exe.ps1` builds a one-file executable with PyInstaller: `web/` is
added as data, `seabreeze` with all its native libraries via `--collect-all`, and the
uvicorn protocol modules as hidden imports. The build runs the tests first, checks
every step's exit code, verifies that a fresh `.exe` exists and writes
`THIRD_PARTY_LICENSES.txt`.

The default build keeps a console window: it shows the URL, and closing it stops the
server. `run.py` redirects output to a log file when there is no console (the
`-Windowed` build), because uvicorn's logging fails without stdout.

## Diagnostics and driver installation

`spectro/diagnostics.py` explains a fallback to the simulator: which seabreeze backend
loads (python-seabreeze silently falls back from `cseabreeze`, which on Windows only sees
devices bound to Ocean Optics' **WinUSB** driver, to `pyseabreeze`), the devices it
lists, and on Windows the PnP status and driver service of every `VID_2457` device
(PowerShell `Get-PnpDevice`, no administrator rights needed). `hints()` turns that into
next steps.

`spectro/driver.py` installs the missing driver: it downloads python-seabreeze's
package of Ocean Optics' WHQL-signed `OOI_*.inf/.cat` files from a **fixed commit**,
refuses it unless the SHA-256 matches, rejects unsafe paths in the ZIP, selects only the
`.inf` files listing the connected devices' hardware IDs (no Windows XP variants), and
runs `pnputil /add-driver … /install` in a separate elevated PowerShell (`-Verb RunAs`,
so Windows shows its administrator prompt; declining it installs nothing).

## Example spectra

`web/examples/` holds real spectra recorded with the lab's USB2000+ (CSV plus
`index.json`), served as static files and bundled into the executable. The page loads
them on demand; they carry mean and SEM only (no scans, hence no histograms) and the
calibration they were recorded with, which the calibration panel uses as reference in
practice mode.

## Windows setup scripts

`windows/ocean-optics-setup/` holds PowerShell 5.1 scripts (the version preinstalled on
Windows). Windows PowerShell does not stop on failing native commands even with
`$ErrorActionPreference = 'Stop'`, so every call goes through `Invoke-Native`, which
checks `$LASTEXITCODE`. The scripts self-elevate, wait for the elevated copy and pass
its exit code back. `Verify.ps1` runs its Python check from a temporary file because
PowerShell 5.1 strips double quotes from native command arguments.

## Design decisions in brief

- **Local only, no authentication.** A lab PC runs one instrument for the students at
  it. Network access would need authentication and locking between users; see
  [SECURITY.md](../SECURITY.md).
- **Averaging and smoothing in software**, not in the spectrometer firmware, so every
  model and the simulator behave the same.
- **Reject rather than queue** a second measurement: a queued half-hour measurement
  would surprise everyone.
- **Live averaging cap, not an exposure cap**: the 30 s limit applies only when
  averaging 2 or more scans, so single long exposures remain possible for
  measurements.
