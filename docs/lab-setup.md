# Lab setup guide: preparing a Windows PC

This guide is for instructors and IT staff who set up a lab PC so that students can
use the spectrometer dashboard. It takes you from a fresh Windows PC to a desktop
icon that starts the dashboard.

**Supported hardware:** Ocean Optics / Ocean Insight classic-series USB spectrometers
(USB2000/USB2000+, USB4000, Flame-S/T, HR2000/HR2000+, HR4000, Maya, QE, NIRQuest, …).
They all appear on USB with vendor ID `2457` (for example `PID_101E` = USB2000+,
`PID_1022` = USB4000). Ocean's newer ST, SR and HR series use vendor ID `0999` and are
not covered by the setup scripts. The software targets the USB2000+ used
in the Freiburg lab; so far it has been tested with the built-in simulator only, so
reports from real setups, for any model, are very welcome (see
[CONTRIBUTING.md](../CONTRIBUTING.md)).

## Overview

| Step | What | Where |
|---|---|---|
| 1 | Install the USB driver and adjust power settings | `windows/ocean-optics-setup/Install.ps1` |
| 2 | Check that the spectrometer works | `windows/ocean-optics-setup/Verify.ps1` |
| 3 | Build the dashboard executable (once, on any Windows PC) | `spectro-dashboard/packaging/build_exe.ps1` |
| 4 | Put the executable on the lab PC | copy `dist\` |

## Requirements

- Windows 10 or 11, 64-bit, with local **administrator** rights for steps 1–2.
- Internet access for the default driver path (Python, pip and the driver download).
  Behind a proxy, set `HTTP_PROXY` / `HTTPS_PROXY` first, or use a vendor installer
  (see below).
- A copy of this repository on the PC: *Code → Download ZIP* on GitHub, or `git clone`.

## Step 1: driver and power settings

Open PowerShell in `windows\ocean-optics-setup` and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install.ps1
```

It asks for administrator rights if needed, then:

1. checks the system;
2. disables **USB selective suspend** in the active power plan, so that Windows does
   not power down the spectrometer during long exposures;
3. installs the **USB driver**. By default this uses the open-source path: it installs
   Python via winget if necessary, creates an environment in
   `C:\ProgramData\OceanOptics\venv` with python-seabreeze and runs its driver
   installer;
4. runs the device check from step 2.

It prints **Done** only if every step succeeded; otherwise it stops at the first
failure with a red error and exit code 1. A full log is written to
`C:\ProgramData\OceanOptics\logs\`.

**Using Ocean Insight's own driver instead.** If your lab already uses OceanView,
place its installer in `windows\ocean-optics-setup\vendor\` (it is proprietary and
not included here), list it in `config.psd1` and run
`.\Install.ps1 -DriverSource Vendor`. See
[the setup package README](../windows/ocean-optics-setup/README.md) for all options,
configuration and exit codes.

## Step 2: check the spectrometer

Plug the spectrometer into a USB port directly on the PC (not an unpowered hub) and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\Verify.ps1
```

It lists the device and its USB hardware ID (`USB\VID_2457&PID_…`, which identifies
the model), disables Windows' per-device USB power saving for it, and acquires one
test spectrum through python-seabreeze.

| Result | Meaning | What to do |
|---|---|---|
| exit code 0, *device working* | A test spectrum was acquired. | Continue with step 3. |
| exit code 2, *no device connected* | Windows does not see a `VID_2457` device. | Check the cable and port; try another port. |
| exit code 1, *device NOT usable* | The device is visible but the driver status is not OK, or seabreeze could not read a spectrum. | Re-run `Install.ps1`; see [Troubleshooting](#troubleshooting). |
| exit code 3, *not tested with software* | The device is visible, but no python-seabreeze environment exists to test it (vendor-only setup). | Run `Install.ps1 -DriverSource Both`, or test with the dashboard. |

## Step 3: build the dashboard executable

You need this only once per version, on any Windows PC with Python 3.10–3.13 (it does
not have to be a lab PC). Alternatively, download the executable built by the
project's CI (the *windows-exe* artifact of a workflow run on GitHub).

```powershell
cd spectro-dashboard
powershell -ExecutionPolicy Bypass -File .\packaging\build_exe.ps1
```

The script creates a build environment, runs the tests, builds
`dist\SpectrometerDashboard.exe` with PyInstaller and writes the license files next
to it. It exits with code 1 if any step fails.

## Step 4: install on the lab PC

1. Copy the contents of `dist\` (the `.exe` and the license files) to the lab PC, e.g.
   to `C:\Program Files\SpectrometerDashboard\`.
2. Create a desktop shortcut to the `.exe` for the students.
3. Start it once yourself. Check that the badge at the top right shows the
   spectrometer model and not **SIMULATED**.

Notes:

- The executable is **not code-signed**. On first start, Windows SmartScreen may show
  *"Windows protected your PC"*; choose *More info → Run anyway*, or sign the executable
  according to your institution's policy.
- The dashboard listens on `127.0.0.1:8777` only, so it is not reachable from the
  network. Use `--port` in the shortcut if that port is taken.
- Only one program can use the spectrometer at a time: close OceanView (or a second
  copy of the dashboard) before starting.

Command-line options (for the shortcut's *Target* field):

| Option | Effect |
|---|---|
| `--port 8777` | Port of the local web server |
| `--sim` | Use the simulator even if hardware is present (demos, training) |
| `--no-browser` | Do not open a browser window on start |

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Badge shows **SIMULATED (no hardware found)** | Hover over the badge for the reason. Usually the spectrometer is unplugged, used by another program, or the driver is missing: run `Verify.ps1`. |
| `Verify.ps1`: device visible, but seabreeze sees nothing | The driver bound to the device does not suit python-seabreeze's default backend. Re-run `Install.ps1 -DriverSource Seabreeze`. As a last resort python-seabreeze documents binding a WinUSB driver with [Zadig](https://zadig.akeo.ie/) and using its `pyseabreeze` backend. |
| Device appears as *Unknown device* in Device Manager | No driver installed: run `Install.ps1`. |
| `Install.ps1` fails at `pip install` or `winget` | No internet access or a proxy: set `HTTP_PROXY` / `HTTPS_PROXY`, or use a vendor installer. The log in `C:\ProgramData\OceanOptics\logs\` has the details. |
| Spectra drop out during long exposures | USB power saving: re-run `Install.ps1` (after switching power plans the setting must be applied again) and `Verify.ps1` with the device plugged in. |
| Browser shows *can't reach this page* | The dashboard is not running (console window closed) or uses another port. |

## Status

The setup scripts have been reviewed, CI checks their syntax on Windows, and their
embedded Python check has been tested against a stand-in for python-seabreeze. They
have **not yet been run on a real lab PC with a spectrometer**. Please watch the first
run on a new PC and report problems.
