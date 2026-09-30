"""Hardware-agnostic spectrometer interface.

Both the real (python-seabreeze) and the simulated backend implement this, so
the rest of the app never imports seabreeze directly and always runs -- with or
without hardware.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class SpectrometerBackend(ABC):
    """Minimal interface the acquisition layer depends on."""

    #: Human-readable model name, e.g. "USB2000PLUS" or "Simulated USB2000+".
    model: str
    #: Device serial number if known, else None.
    serial: str | None

    @abstractmethod
    def wavelengths(self) -> np.ndarray:
        """Per-pixel wavelength axis in nm (constant for a given device)."""

    @abstractmethod
    def intensities(self) -> np.ndarray:
        """Acquire and return one raw spectrum (counts), one value per pixel."""

    @abstractmethod
    def set_integration_time_ms(self, ms: float) -> None:
        """Set the integration (exposure) time in milliseconds."""

    @property
    @abstractmethod
    def integration_time_limits_ms(self) -> tuple[float, float]:
        """(min, max) supported integration time in ms."""

    def close(self) -> None:  # optional override
        """Release the device. Safe to call more than once."""
