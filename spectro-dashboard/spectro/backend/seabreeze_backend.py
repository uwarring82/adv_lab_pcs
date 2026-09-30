"""Real hardware backend via python-seabreeze.

seabreeze is imported lazily so this module can be imported on machines without
it installed (e.g. during development on macOS) -- the import only happens when
you actually open a device.
"""
from __future__ import annotations

import numpy as np

from .base import SpectrometerBackend


class SeabreezeSpectrometer(SpectrometerBackend):
    def __init__(self, device=None):
        import seabreeze.spectrometers as sb  # lazy: only needed with hardware

        if device is None:
            devices = sb.list_devices()
            if not devices:
                raise RuntimeError(
                    "No Ocean Optics spectrometer found. Check the USB connection "
                    "and that the driver is installed (run windows/ocean-optics-setup)."
                )
            device = devices[0]

        self._spec = sb.Spectrometer(device)
        self.model = self._spec.model
        try:
            self.serial = self._spec.serial_number
        except Exception:
            self.serial = None
        self._wl = np.asarray(self._spec.wavelengths(), dtype=float)

    @staticmethod
    def list_devices() -> list[str]:
        """Return string descriptions of connected devices (for diagnostics)."""
        import seabreeze.spectrometers as sb

        return [str(d) for d in sb.list_devices()]

    def wavelengths(self) -> np.ndarray:
        return self._wl.copy()

    def set_integration_time_ms(self, ms: float) -> None:
        self._spec.integration_time_micros(int(round(ms * 1000)))

    @property
    def integration_time_limits_ms(self) -> tuple[float, float]:
        try:
            lo, hi = self._spec.integration_time_micros_limits
            return (lo / 1000.0, hi / 1000.0)
        except Exception:
            return (1.0, 65000.0)

    def intensities(self) -> np.ndarray:
        # Raw counts, as in the lab notebook: no on-device dark or nonlinearity correction.
        return np.asarray(
            self._spec.intensities(correct_dark_counts=False, correct_nonlinearity=False),
            dtype=float)

    def close(self) -> None:
        try:
            self._spec.close()
        except Exception:
            pass
