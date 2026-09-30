# Development guide

How to work on the code. For the design, read [architecture.md](architecture.md) first.

## Setup

Python 3.10 or newer on any OS. The simulator replaces the spectrometer, so no hardware
is needed for development.

```bash
cd spectro-dashboard
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python run.py --sim                              # http://127.0.0.1:8777/ , API docs at /docs
```

`run.py` options: `--sim`, `--port`, `--host`, `--no-browser`. Without `--sim` it tries
the hardware and falls back to the simulator.

## Repository layout

```
spectro-dashboard/
  run.py                      entry point (server + browser); frozen into the .exe
  spectro/
    app.py                    FastAPI app: REST, WebSocket, CSV, static files, error mapping
    acquisition.py            AcquisitionManager: limits, live processing, measurements
    models.py                 pydantic request/response models (also the /docs schema)
    backend/                  SpectrometerBackend interface, seabreeze and simulator
  web/                        dashboard: index.html, app.js, style.css, spectrum_color.js
    lib/                      vendored uPlot (+ its license)
  examples/student_client.py  scripting example for students
  tests/                      pytest suite
  packaging/build_exe.ps1     Windows executable build
windows/ocean-optics-setup/   PowerShell setup and verification for lab PCs
docs/                         documentation
.github/                      CI workflow, issue and pull-request templates
```

## Tests

```bash
cd spectro-dashboard
pytest
```

The suite runs in about a second and needs no hardware:

- `tests/test_acquisition.py` covers statistics (mean/SEM against numpy), limits,
  boxcar length and edge handling, dark-reference rules, histogram validation and bin
  capping, and measurement concurrency. It uses two fake backends: `SequenceBackend`
  (replays given scans, for exact expected values) and `GatedBackend` (blocks a scan
  until released, to test concurrency without timing).
- `tests/test_api.py` covers the HTTP layer with FastAPI's `TestClient` and a
  non-sleeping simulator: status codes, CSV consistency, WebSocket frames.

Write a regression test for every bug you fix, and add a fake backend if you need
specific data rather than relying on sleeps.

The JavaScript has no unit tests. After frontend changes, check the syntax with
`node --check web/app.js` and click through the dashboard in simulator mode: live,
zoom, a measurement, histogram, log axis, wavelength axis and colour strip.

## Adding a spectrometer backend

1. Implement `SpectrometerBackend` (`spectro/backend/base.py`) in a new module, importing
   the vendor library lazily inside `__init__`.
2. Return raw counts from `intensities()` and wavelengths in nm from `wavelengths()`,
   both with one entry per pixel.
3. Hook it into `open_backend()` in `spectro/backend/__init__.py` (and, if it is
   selectable, into `run.py`'s options).
4. Test the manager against it with a fake that has the same shape (pixel count,
   integration limits).

## Frontend

Edit the files in `web/`; reload the page to see changes (the server serves them from
disk). Keep it free of build tools and external CDNs, so it works offline and inside
the executable.

To update uPlot, download `uPlot.iife.min.js`, `uPlot.min.css` and `LICENSE` of the new
version from the npm package (e.g. `https://cdn.jsdelivr.net/npm/uplot@<version>/dist/`),
replace the files in `web/lib/` (the license as `uPlot.LICENSE`) and update the version
in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Windows parts

The PowerShell scripts target **Windows PowerShell 5.1**. Keep these rules:

- Run native commands through `Invoke-Native` (checks `$LASTEXITCODE`); cmdlet errors
  stop the script via `$ErrorActionPreference = 'Stop'`.
- Quote arguments containing `>` or `<` (`'pyinstaller>=6.3'`): unquoted they are
  redirections.
- Do not pass code with double quotes as native arguments (`python -c "..."`);
  PowerShell 5.1 strips them. Write it to a temporary file instead.

Build the executable on Windows with `packaging\build_exe.ps1`; see the
[lab setup guide](lab-setup.md#step-3-build-the-dashboard-executable).

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

| Job | What it checks |
|---|---|
| `tests` | pytest on Ubuntu (Python 3.10, 3.12, 3.13) and Windows (3.12), installing from `requirements-dev.txt` |
| `frontend` | `node --check` on the dashboard's JavaScript |
| `powershell` | parses every `.ps1` with the Windows PowerShell 5.1 parser and runs PSScriptAnalyzer (errors fail the job) |
| `windows-exe` | runs `build_exe.ps1`, starts the executable in simulator mode, checks the API and the bundled web page, and uploads the executable with its license files as the `windows-exe` artifact |

## Releasing

1. Update the version in `spectro-dashboard/spectro/__init__.py` and `CITATION.cff`.
2. Move the *Unreleased* entries in [CHANGELOG.md](../CHANGELOG.md) under the new
   version with the date.
3. Commit, tag (`git tag v0.3.0`) and push the tag.
4. Attach the `windows-exe` artifact of that commit's CI run to a GitHub release.
5. Before announcing a release for lab use, run it once on a real lab PC with a
   spectrometer: `Install.ps1`, `Verify.ps1` (exit code 0), then a measurement in the
   dashboard.
