# Windows setup package for Ocean Optics classic-series spectrometers

Prepares a **Windows 10/11** PC for an **Ocean Optics / Ocean Insight classic-series
USB spectrometer** (USB2000/+, USB4000, Flame-S/T, HR2000/+, HR4000, Maya, QE,
NIRQuest, …; all enumerate under USB `VID_2457`).

This is the reference for the scripts. For a step-by-step walkthrough, from a fresh PC
to the dashboard on the desktop, see the [lab setup guide](../../docs/lab-setup.md).

The default driver path installs the same python-seabreeze version
(`seabreeze==2.10.1`, `pyusb==1.3.1`) that the dashboard and the lab's earlier
analysis code use.

## What it does

`Install.ps1` (self-elevating, idempotent, fully logged) runs:

1. **Environment checks**: admin rights, OS, architecture.
2. **USB power settings**: optionally activates the High Performance plan, then
   disables USB *selective suspend* on the active plan (prevents dropouts during
   long integrations).
3. **Driver install**, per `DriverSource` in `config.psd1`:
   - **Seabreeze** *(open source, no vendor license needed; default via `Both`)*:
     installs Python via winget if missing, creates a shared venv, installs the
     pinned `requirements-spectrometer.txt` and runs `seabreeze_os_setup` to install
     the USB driver.
   - **Vendor**: runs an OceanView/OmniDriver installer you place in `vendor\`
     (proprietary, not included; see [vendor/README.md](vendor/README.md)).
   - **Both** (default) / **None**.
4. **Device check**: runs `Verify.ps1`.

`Verify.ps1` (run **with the device plugged in**) lists the `VID_2457` device and its
hardware ID (identifies the exact model), disables *per-device* USB power saving and
acquires one test spectrum through python-seabreeze.

## Usage

In this folder, in PowerShell (elevation is requested automatically):

```powershell
powershell -ExecutionPolicy Bypass -File .\Install.ps1
```

Then plug in the spectrometer and:

```powershell
powershell -ExecutionPolicy Bypass -File .\Verify.ps1
```

Variants:

```powershell
.\Install.ps1 -DriverSource Seabreeze   # skip vendor installers
.\Install.ps1 -DriverSource None        # power settings + device check only
.\Install.ps1 -SkipPowerTweaks
```

Logs: `C:\ProgramData\OceanOptics\logs\`. Shared venv: `C:\ProgramData\OceanOptics\venv`.

### Exit codes

Every native command's exit code is checked; the first failure stops the script.
When a script relaunches itself elevated, the elevated window stays open at the end
and its exit code is passed back.

| Script | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `Install.ps1` | all steps succeeded ("Done"; a spectrometer that is not plugged in or not software-tested yet is only a warning) | a step failed, or a connected spectrometer is not usable | — | — |
| `Verify.ps1` | spectrometer found and a test spectrum acquired | connected but not usable (driver status or seabreeze check) | no spectrometer connected | enumerates, but not tested with software (no seabreeze venv) |

## Configuration

Edit `config.psd1`: USB vendor ID, driver source, venv path, power-management
switches, winget Python package id and the vendor installers to run.

## Requirements

- Windows 10/11 x64, local **administrator** rights.
- **Internet access** for the Seabreeze path (winget, pip and the driver download).
  Behind a proxy, set `HTTP_PROXY` / `HTTPS_PROXY` first, or use the Vendor path with
  a staged installer.
- `winget` (App Installer), or Python 3.10+ already installed.

## Known limitations

- **Not yet run on a real lab PC with a spectrometer.** CI checks the scripts' syntax
  on Windows, and the embedded Python check was tested against a stand-in for
  python-seabreeze. Watch the first run and treat the `Verify.ps1` output as the
  source of truth.
- **cseabreeze vs. pyseabreeze:** `seabreeze_os_setup` installs the driver that
  python-seabreeze's default (cseabreeze) backend expects. If the device shows in
  Device Manager but seabreeze finds nothing, python-seabreeze documents a fallback:
  its pyseabreeze backend with a WinUSB driver bound via Zadig. That is not automated
  here because Zadig is interactive.
- **Vendor installers:** silent-install switches vary between versions; verify them
  once interactively.
- USB selective suspend is a per-power-plan setting: re-run `Install.ps1` after
  switching plans.

## Files

| File | Purpose |
|------|---------|
| `Install.ps1` | Setup (self-elevating) |
| `Verify.ps1` | Device and software check |
| `config.psd1` | Settings |
| `requirements-spectrometer.txt` | Pinned python-seabreeze stack |
| `vendor/` | Place for proprietary OceanView/OmniDriver installers (ignored by git) |
