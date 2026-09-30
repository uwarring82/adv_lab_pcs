"""Simulated spectrometer.

Produces a plausible USB2000+-like spectrum (broadband lamp baseline + a few
emission lines + shot/read noise) that responds to integration time. Lets the
whole dashboard and API run without any hardware -- for development, teaching,
and demos.
"""
from __future__ import annotations

import time

import numpy as np

from .base import SpectrometerBackend

# USB2000+ is a 2048-pixel detector spanning roughly 340-1025 nm.
_N_PIXELS = 2048
_WL_MIN, _WL_MAX = 340.0, 1025.0

# (center_nm, amplitude_counts, width_nm) -- a few fake emission lines.
_LINES = [
    (436.0, 18000.0, 1.2),   # Hg-like
    (546.1, 30000.0, 1.4),
    (611.6, 12000.0, 1.6),
    (763.5, 22000.0, 2.0),
    (852.1, 9000.0, 2.2),
]


class SimulatedSpectrometer(SpectrometerBackend):
    def __init__(self, seed: int | None = None, realtime: bool = True):
        """``realtime=False`` skips the integration-time sleep (for tests)."""
        self.model = "Simulated USB2000+"
        self.serial = "SIM-0001"
        self._realtime = realtime
        self._wl = np.linspace(_WL_MIN, _WL_MAX, _N_PIXELS)
        self._integration_ms = 100.0
        self._rng = np.random.default_rng(seed)
        # Smooth broadband baseline (blackbody-ish hump), normalised ~1.
        b = np.exp(-((self._wl - 650.0) ** 2) / (2 * 180.0 ** 2))
        self._baseline = 0.15 + 0.85 * b / b.max()

    def wavelengths(self) -> np.ndarray:
        return self._wl.copy()

    def set_integration_time_ms(self, ms: float) -> None:
        lo, hi = self.integration_time_limits_ms
        self._integration_ms = float(np.clip(ms, lo, hi))

    @property
    def integration_time_limits_ms(self) -> tuple[float, float]:
        return (1.0, 65000.0)

    def intensities(self) -> np.ndarray:
        # Block for the integration time like real hardware, so live frame rate
        # and measurement duration behave the same with and without a device.
        if self._realtime:
            time.sleep(self._integration_ms / 1000.0)
        # Signal scales with integration time (counts proportional to exposure).
        scale = self._integration_ms / 100.0
        signal = 1500.0 * self._baseline * scale
        for c, amp, w in _LINES:
            signal += amp * scale * np.exp(-((self._wl - c) ** 2) / (2 * w ** 2))
        # Shot noise (Poisson-like) + constant read noise; clip to detector range.
        noise = self._rng.normal(0.0, np.sqrt(np.maximum(signal, 1.0))) + \
            self._rng.normal(0.0, 12.0, size=signal.shape)
        # Integer ADC counts, 16-bit range, like the real detector.
        return np.clip(np.rint(signal + noise + 120.0), 0.0, 65535.0)
