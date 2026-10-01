Spectrometer dashboard for Ocean Optics classic-series USB spectrometers (USB2000+, USB4000, Flame, HR2000+, …). Changes: see [CHANGELOG.md](https://github.com/uwarring82/adv_lab_pcs/blob/main/CHANGELOG.md).

> **Pre-release** until it has been checked with a real spectrometer. Reports from real setups are very welcome: please open an issue (there is a *Hardware report* template).

## Download and start

1. Download the **ZIP** below (no GitHub account needed) and unzip it.
2. Start **`SpectrometerDashboard.exe`**. A console window opens and the dashboard appears in the browser at http://127.0.0.1:8777/. Closing the console window stops it.
3. The executable is not code-signed. If Windows shows *"Windows protected your PC"*, choose **More info → Run anyway**.

The badge at the top right should show the spectrometer model. If it says **SIMULATED**, no spectrometer was found; hover over the badge for the reason. Usually the spectrometer is unplugged, another program such as OceanView is using it (close it first), or the USB driver is missing. If OceanView works with the spectrometer on that PC, the driver is very likely already suitable; otherwise see the [lab setup guide](https://github.com/uwarring82/adv_lab_pcs/blob/main/docs/lab-setup.md).

## What to try

Live view, integration time, a short measurement (e.g. 50 scans), the histogram of a channel (click on a peak) and the CSV export. See the [student guide](https://github.com/uwarring82/adv_lab_pcs/blob/main/docs/student-guide.md).

## Contents of the ZIP

- `SpectrometerDashboard.exe`: Windows 10/11, 64-bit
- `LICENSE.txt` (MIT), `THIRD_PARTY_NOTICES.md`, `THIRD_PARTY_LICENSES.txt`: licenses of the bundled components; keep them with the executable when you pass it on
