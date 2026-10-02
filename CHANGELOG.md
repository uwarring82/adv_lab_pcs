# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.1] - 2026-10-02

First feedback from a real lab PC: the dashboard fell back to the simulator without
saying why.

### Added

- **Connection diagnostics**: when no spectrometer is found, the dashboard explains why
  and what to do. It checks which seabreeze backend loads, which devices it sees and, on
  Windows, every Ocean Optics USB device with its driver (e.g. a Jungo driver from
  older Ocean software instead of WinUSB). Opens automatically, and from the badge;
  *Copy report* gives a text to send. Also at `GET /api/diagnostics`.
- **Retry hardware** (`POST /api/reconnect`): look for the spectrometer again, e.g.
  after closing OceanView, without restarting.
- The console window prints the spectrometer, or the reason for the fallback, at
  start-up.
- CI starts the executable without `--sim` and checks that the hardware backend loads
  and the USB query works inside the executable.

### Fixed

- The page could become wider than the window and be cut off on the right after the
  window was resized; the plots now follow their container's size.

## [0.3.0] - 2026-10-01: first public version

### Spectrometer dashboard (`spectro-dashboard/`)

- Local FastAPI service with a browser dashboard, packaged as a single Windows `.exe`.
- Live view: mean ± SEM over *scans to average*, dark subtraction, boxcar smoothing,
  streamed over a WebSocket.
- Statistical measurement: N raw scans → per-channel mean and standard error of the
  mean, with a progress indicator, as in the lab's earlier Jupyter workflow.
- Per-channel intensity histograms (`numpy` bin rules or a fixed number of bins).
- Notebook-style figures: saturation line at 2¹⁶, channel or wavelength axis, log
  scale, zoom that survives live updates, and a colour illustration of the visible
  spectrum (CIE 1931).
- CSV export and a documented HTTP API (`/docs`) for student scripts.
- Validation of every request against memory, time and detector limits; clear `422` /
  `409` errors, shown in the dashboard.
- Built-in simulator (same interface as the hardware backend) for development and
  teaching without a device.
- The web page is served with `Cache-Control: no-cache`, so browsers never show a
  stale page after the executable is updated.
- Test suite (pytest) with fake backends for statistics, limits and concurrency.

### Windows lab-PC setup (`windows/ocean-optics-setup/`)

- `Install.ps1`: USB power settings and driver installation (open-source
  python-seabreeze path or a vendor installer you provide), with a checked exit code
  for every step.
- `Verify.ps1`: finds the device, disables per-device USB power saving and acquires a
  test spectrum; distinct exit codes for working / not usable / not connected /
  untested.

### Project

- MIT license, third-party notices, contribution guide, security policy, citation
  file, documentation in `docs/` and a CI workflow.
- Tagged versions are published automatically as GitHub pre-releases (ZIP with the
  executable and its licenses, plus a SHA-256 checksum), downloadable without a
  GitHub account.
