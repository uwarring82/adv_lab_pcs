"""Spectrometer backends and selection helper."""
from __future__ import annotations

from .base import SpectrometerBackend


def open_backend(prefer_sim: bool = False) -> SpectrometerBackend:
    """Return a ready spectrometer backend.

    If ``prefer_sim`` is True, always return the simulator. Otherwise try real
    hardware via seabreeze and fall back to the simulator if that is unavailable
    (seabreeze not installed, or no device found).
    """
    if prefer_sim:
        from .sim_backend import SimulatedSpectrometer
        return SimulatedSpectrometer()

    try:
        from .seabreeze_backend import SeabreezeSpectrometer
        return SeabreezeSpectrometer()
    except Exception as exc:  # no seabreeze, or no device
        from .sim_backend import SimulatedSpectrometer
        sim = SimulatedSpectrometer()
        sim._fallback_reason = str(exc)  # type: ignore[attr-defined]
        return sim


__all__ = ["SpectrometerBackend", "open_backend"]
