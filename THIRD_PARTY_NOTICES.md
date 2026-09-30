# Third-party notices

This project is MIT-licensed (see [LICENSE](LICENSE)). It includes or builds on the
following third-party work.

## Included in this repository

### uPlot 1.6.31

- Files: `spectro-dashboard/web/lib/uPlot.iife.min.js`, `spectro-dashboard/web/lib/uPlot.min.css`
- Source: <https://github.com/leeoniya/uPlot>
- License: MIT, Copyright (c) 2022 Leon Sorokin. Full text:
  [`spectro-dashboard/web/lib/uPlot.LICENSE`](spectro-dashboard/web/lib/uPlot.LICENSE)

### CIE 1931 colour-matching functions

`spectro-dashboard/web/spectrum_color.js` contains the CIE 1931 2° standard
observer colour-matching functions (380–780 nm, 5 nm steps) and the standard
XYZ → linear sRGB matrix. These are published reference data of the
International Commission on Illumination (CIE); the conversion code is part of
this project.

## Used at run time (not included in the repository)

Installed with `pip` from `requirements.txt`:

| Package | License |
|---|---|
| [python-seabreeze](https://github.com/ap--/python-seabreeze) | MIT |
| [FastAPI](https://github.com/fastapi/fastapi) | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause |
| [Starlette](https://github.com/encode/starlette) | BSD-3-Clause |
| [pydantic](https://github.com/pydantic/pydantic) | MIT |
| [NumPy](https://numpy.org) | BSD-3-Clause (plus bundled libraries, see its license file) |
| [pyusb](https://github.com/pyusb/pyusb) | BSD-3-Clause |

## In the packaged Windows executable

`SpectrometerDashboard.exe` (built by `spectro-dashboard/packaging/build_exe.ps1`)
contains a Python interpreter and the packages above. The build writes their
license texts to `dist/THIRD_PARTY_LICENSES.txt`; distribute that file together
with the executable.

The executable is produced with [PyInstaller](https://pyinstaller.org). Its
bootloader is licensed under the GPL-2.0 with an exception that explicitly allows
distributing the resulting executables under any license, including this
project's MIT license.

## Not included: Ocean Insight software

OceanView, OmniDriver and Ocean Insight's USB drivers are proprietary and are
**not** part of this repository. The optional `windows/ocean-optics-setup/vendor/`
folder is only a place to put installers you obtained yourself.

## Trademarks

Ocean Optics, Ocean Insight, OceanView and the model names of their
spectrometers (e.g. USB2000+, Flame) are trademarks of their respective owners.
They are used here only to describe compatible hardware. This project is not
affiliated with, endorsed by or supported by Ocean Insight.
