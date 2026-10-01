# adv_lab_pcs

**A browser dashboard and HTTP API that turn an Ocean Optics USB spectrometer into a
teaching instrument, plus scripts to prepare Windows lab PCs for it.**

Developed for the advanced lab courses at the Institute of Physics, University of
Freiburg, and usable in any lab with an Ocean Optics classic-series spectrometer
(USB2000+, USB4000, Flame, HR2000+, …).

![Spectrometer dashboard: 200-scan measurement with standard errors, colour strip of the visible spectrum and the intensity histogram of one channel](docs/images/dashboard.png)

## Features

- **Live view** with scan averaging (mean ± standard error), dark subtraction and
  boxcar smoothing.
- **Statistical measurements**: N raw scans → per-channel mean and standard error of
  the mean, with **intensity histograms** of individual channels. Students see the
  detector's noise statistics directly.
- **Figures in the style of the lab's analysis notebooks**: saturation line at 2¹⁶,
  channel or wavelength axis, log scale, zoom, and a **colour illustration of the
  visible spectrum** (CIE 1931).
- **CSV export** and a documented **HTTP API** (`/docs`), so students can script their
  own measurements in Python or any other language.
- **Safe by default**: runs locally on the lab PC, validates every request against
  memory and time limits, and allows one measurement at a time.
- **One-click deployment**: a single Windows `.exe`; PowerShell scripts install the
  USB driver and verify the spectrometer.
- **No hardware needed to try it**: a built-in simulator behaves like a USB2000+.

## Try it (any OS, no spectrometer)

Requires Python 3.10+. Clone or download this repository, then:

```bash
cd adv_lab_pcs/spectro-dashboard
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py --sim
```

Your browser opens <http://127.0.0.1:8777/> with a simulated spectrometer; the API
documentation is at <http://127.0.0.1:8777/docs>. Click **Measure**, then click a
peak to see its histogram.

## Use it in a lab

1. Prepare the Windows PC: `windows/ocean-optics-setup/Install.ps1` installs the USB
   driver and power settings, and `Verify.ps1` checks the spectrometer.
2. Download `SpectrometerDashboard.exe` from the
   [Releases](https://github.com/uwarring82/adv_lab_pcs/releases) page (no GitHub
   account needed), or build it with `spectro-dashboard/packaging/build_exe.ps1`.
3. Put the executable on the lab PC's desktop.

The [lab setup guide](docs/lab-setup.md) walks through every step.

## Documentation

| Guide | For |
|---|---|
| [Student guide](docs/student-guide.md) | Using the dashboard in a lab course, statistics, dark spectra, first scripts |
| [HTTP API reference](docs/api.md) | Endpoints, data formats, limits and errors |
| [Lab setup guide](docs/lab-setup.md) | Preparing a Windows PC, building and deploying the executable, troubleshooting |
| [Architecture](docs/architecture.md) | How the pieces fit together, and why |
| [Development guide](docs/development.md) | Running the tests, adding a backend, CI, releasing |

## Repository layout

```
spectro-dashboard/            the dashboard: FastAPI service, web page, simulator, tests, .exe build
windows/ocean-optics-setup/   PowerShell scripts: USB driver, power settings, device check
docs/                         documentation
```

## Project status

Version 0.3.0, the first public version. The dashboard, API and statistics are covered
by an automated test suite and have been tested with the simulator, including in a
browser; CI builds and smoke-tests the Windows executable on every push. **The software has not yet
been run with a real spectrometer, and the setup scripts not yet on a real lab PC.**
Reports from real setups are the most useful contribution right now.

## Contributing

Bug reports, hardware reports ("works with my Flame-S") and pull requests are welcome.
See [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md).
Please report security problems privately, as described in [SECURITY.md](SECURITY.md).

## Citing

If you use this software in teaching or research, please cite it; see
[CITATION.cff](CITATION.cff) (GitHub shows a *Cite this repository* button).

## License

[MIT](LICENSE) © 2026 Ulrich Warring. Third-party components and their licenses are
listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

This project is not affiliated with or endorsed by Ocean Insight. Ocean Optics, Ocean
Insight, OceanView and the spectrometer model names are trademarks of their respective
owners.

## Acknowledgments

- The advanced lab courses at the Institute of Physics, University of Freiburg, whose
  earlier analysis notebooks defined the statistics and figures used here.
- [python-seabreeze](https://github.com/ap--/python-seabreeze) for open-source access to
  Ocean Optics spectrometers, and [uPlot](https://github.com/leeoniya/uPlot) for fast
  plotting.
