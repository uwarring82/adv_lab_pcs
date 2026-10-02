"""Wavelength calibration.

Ocean Optics spectrometers store a polynomial  lambda(p) = c0 + c1 p + c2 p^2 + c3 p^3
(p = pixel / channel) in the device; seabreeze returns the resulting wavelengths. A
custom calibration replaces it, either from entered coefficients or from a fit to
reference lines (pixel <-> known wavelength). Custom calibrations are saved per
device (model + serial) so they survive restarts, and the factory calibration is
always kept for comparison.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from numpy.polynomial import polynomial as P

MAX_ORDER = 3


class CalibrationError(ValueError):
    """Invalid calibration request."""


def evaluate(coefficients, pixels) -> np.ndarray:
    return P.polyval(np.asarray(pixels, dtype=np.float64), np.asarray(coefficients, dtype=np.float64))


def factory_coefficients(wavelengths: np.ndarray) -> list[float]:
    """The device polynomial recovered from its wavelengths (exact for a cubic).
    Terms that change the wavelength by less than 1e-6 nm across the detector are
    rounding noise of the fit and reported as 0."""
    pixels = np.arange(wavelengths.size, dtype=np.float64)
    coefficients = P.polyfit(pixels, wavelengths, MAX_ORDER)
    span = max(wavelengths.size - 1, 1)
    return [0.0 if abs(c) * span ** k < 1e-6 else float(c) for k, c in enumerate(coefficients)]


def check_coefficients(coefficients, n_pixels: int) -> list[float]:
    c = [float(x) for x in coefficients]
    if len(c) == 0 or len(c) > MAX_ORDER + 1 or not all(np.isfinite(c)):
        raise CalibrationError("Give 1 to 4 finite coefficients c0, c1, c2, c3.")
    c += [0.0] * (MAX_ORDER + 1 - len(c))
    wl = evaluate(c, np.arange(n_pixels))
    if not np.all(np.diff(wl) > 0):
        raise CalibrationError("The calibration must give increasing wavelengths across the detector.")
    if wl[0] <= 0:
        raise CalibrationError("The calibration gives non-positive wavelengths.")
    return c


def fit_lines(lines, n_pixels: int, order: int | None = None) -> dict:
    """Fit lambda(p) to reference lines [(pixel, wavelength_nm), ...]."""
    if len(lines) < 2:
        raise CalibrationError("At least 2 reference lines are needed.")
    p = np.array([float(l[0]) for l in lines])
    wl = np.array([float(l[1]) for l in lines])
    if not (np.all(np.isfinite(p)) and np.all(np.isfinite(wl))):
        raise CalibrationError("Pixel and wavelength must be numbers.")
    if np.any(p < 0) or np.any(p > n_pixels - 1):
        raise CalibrationError(f"Pixels must be between 0 and {n_pixels - 1}.")
    if np.unique(np.round(p, 6)).size != p.size:
        raise CalibrationError("Each reference line needs a different pixel.")
    if np.any(wl <= 0):
        raise CalibrationError("Wavelengths must be positive.")
    order = min(MAX_ORDER, len(lines) - 1) if order is None else int(order)
    if not 1 <= order <= MAX_ORDER:
        raise CalibrationError(f"The polynomial order must be between 1 and {MAX_ORDER}.")
    if len(lines) < order + 1:
        raise CalibrationError(f"Order {order} needs at least {order + 1} reference lines.")
    coefficients = [float(c) for c in P.polyfit(p, wl, order)]
    coefficients = check_coefficients(coefficients, n_pixels)
    return {
        "coefficients": coefficients,
        "order": order,
        "lines": [{"pixel": float(a), "wavelength_nm": float(b)} for a, b in zip(p, wl)],
    }


def compare(factory: list[float], custom: list[float] | None, lines, n_pixels: int) -> dict:
    """Side-by-side view of factory and custom calibration for students: each
    reference line under both, RMS of both, and their largest difference."""
    rows = []
    for line in lines or []:
        px, ref = line["pixel"], line["wavelength_nm"]
        f = float(evaluate(factory, px))
        row = {"pixel": px, "wavelength_nm": ref, "factory_nm": f, "factory_residual_nm": f - ref}
        if custom is not None:
            c = float(evaluate(custom, px))
            row.update(custom_nm=c, custom_residual_nm=c - ref)
        rows.append(row)

    def rms(key):
        vals = [r[key] for r in rows if key in r]
        return float(np.sqrt(np.mean(np.square(vals)))) if vals else None

    out = {"lines": rows, "factory_rms_nm": rms("factory_residual_nm"),
           "custom_rms_nm": rms("custom_residual_nm"), "max_difference_nm": None,
           "max_difference_pixel": None}
    if custom is not None:
        pixels = np.arange(n_pixels)
        diff = evaluate(custom, pixels) - evaluate(factory, pixels)
        i = int(np.argmax(np.abs(diff)))
        out.update(max_difference_nm=float(diff[i]), max_difference_pixel=i)
    return out


def default_store_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "SpectrometerDashboard" / "calibrations.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "spectrometer-dashboard" / "calibrations.json"


class CalibrationStore:
    """Custom calibrations per device, in a JSON file (or in memory if path is None)."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self._mem: dict = {}

    def _read(self) -> dict:
        if self.path is None:
            return self._mem
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            return {}  # unreadable file: start from factory calibrations

    def load(self, key: str) -> dict | None:
        return self._read().get(key)

    def save(self, key: str, calibration: dict | None) -> str | None:
        """Store (or with None remove) a calibration; returns an error message or None."""
        data = dict(self._read())
        if calibration is None:
            data.pop(key, None)
        else:
            data[key] = {**calibration, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        if self.path is None:
            self._mem = data
            return None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, self.path)
            return None
        except OSError as exc:
            return f"Could not save the calibration to {self.path}: {exc}"
