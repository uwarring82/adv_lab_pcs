# Example spectra

Real spectra recorded in 2025 in the advanced lab at the University of Freiburg with an
Ocean Optics USB2000+ (visible range, about 395–728 nm). The dashboard lists them under
*Examples*; they work without a spectrometer.

| File | Content |
|---|---|
| `hg.csv` | Mercury spectral lamp (calibration lines; the 546 nm line is saturated) |
| `cd.csv` | Cadmium spectral lamp |
| `ne.csv` | Helium-neon discharge lamp (neon lines) |
| `na.csv` | Sodium lamp (D lines) |
| `sun.csv` | Sunlight with Fraunhofer lines |
| `candle.csv` | Candle flame |
| `phone.csv` | Smartphone screen showing white |
| `lamp.csv` | Desk lamp |
| `i2.csv` | Absorption of iodine vapour |

Each file has comment lines (`#`) with the recording date, the number of scans and the
wavelength calibration, then the columns `channel, wavelength_nm, mean_counts,
sem_counts, std_counts` (mean over N scans; `std` with ddof = 1; `sem = std / √N`).
The integration times were not recorded.

The wavelengths use the lab's calibration polynomial
λ(p) = 395.4 + 0.1897 p − 1.231·10⁻⁵ p² − 5.2·10⁻¹⁰ p³ (p = channel). `index.json`
describes the files for the dashboard. The data are part of this project and covered by
its MIT license.
