# Spectrometer dashboard

A local web app for Ocean Optics classic-series USB spectrometers: live view,
N-scan statistics with standard errors, per-channel histograms, a colour
illustration of the visible spectrum, CSV export and an HTTP API for scripts.
Packaged as a single Windows `.exe`; runs on any OS with the built-in simulator.

- **Using it** (students): [docs/student-guide.md](../docs/student-guide.md)
- **HTTP API, limits and errors:** [docs/api.md](../docs/api.md), or `/docs` in the running app
- **Deploying to a lab PC:** [docs/lab-setup.md](../docs/lab-setup.md)
- **How it works:** [docs/architecture.md](../docs/architecture.md)

## Run from source

Python 3.10+:

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py --sim        # simulator; drop --sim to use a connected spectrometer
```

The dashboard opens at <http://127.0.0.1:8777/>. Options: `--port`, `--host`,
`--no-browser`, `--sim`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

About a second, no hardware needed. See [docs/development.md](../docs/development.md).

## Build the Windows executable

On Windows, after preparing the drivers with
[`windows/ocean-optics-setup`](../windows/ocean-optics-setup/):

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build_exe.ps1
# -> dist\SpectrometerDashboard.exe plus LICENSE.txt, THIRD_PARTY_NOTICES.md, THIRD_PARTY_LICENSES.txt
```

The build runs the tests first (`-SkipTests` to skip) and exits with code 1 if any
step fails or no fresh `.exe` was produced. The executable opens a console window
showing the URL; closing it stops the server. `-Windowed` builds without the console
(output then goes to `%TEMP%\spectrometer-dashboard.log`). CI builds and smoke-tests
the executable on every push; tagged versions are published on the
[Releases](https://github.com/uwarring82/adv_lab_pcs/releases) page.

## Layout

```
run.py                     entry point (start server + open browser)
spectro/
  app.py                   FastAPI: REST + WebSocket + CSV + static files
  acquisition.py           limits, live processing, N-scan statistics (thread-safe)
  calibration.py           wavelength calibration: fit, comparison, saved per device
  diagnostics.py           why no spectrometer is found, with next steps
  driver.py                Windows: install Ocean Optics' signed WinUSB driver
  models.py                pydantic schema (also drives /docs)
  backend/
    base.py                SpectrometerBackend interface
    seabreeze_backend.py   real hardware (python-seabreeze, lazy import, raw counts)
    sim_backend.py         simulated USB2000+ (no hardware needed)
web/                       dashboard (index.html, app.js, style.css); no build step
  spectrum_color.js        wavelength -> sRGB (CIE 1931) for the colour strip
  examples/                real spectra from the lab (CSV + index.json)
  lib/                     uPlot 1.6.31 (MIT), vendored so it works offline
examples/student_client.py scripting example
tests/                     pytest suite
packaging/build_exe.ps1    PyInstaller build
```

## Status

Tested with the simulator (pytest suite, all endpoints, the dashboard in a headless
browser) and, as of 0.3.1, with a real USB2000+ on Windows 11 (live view, averaging,
measurements, CSV). The 0.4.0 additions (calibration, driver installation, dark
subtraction in measurements) have not been tried on hardware yet. Please report results
from real setups (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
