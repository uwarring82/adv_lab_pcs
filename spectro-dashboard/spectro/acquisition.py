"""Acquisition manager: owns the device, applies processing, is thread-safe.

The hardware is single-threaded, so every device touch goes through one lock.

Two modes, following the lab's earlier USB2000 analysis notebook:
  * live        -- mean +- SEM over ``scans_to_average`` scans, with optional dark
                   subtraction and boxcar smoothing, for the preview;
  * measurement -- N raw scans -> per-channel mean, standard error of the mean
                   (std with ddof=1, divided by sqrt(N)), and the scan block kept
                   for per-channel intensity histograms (np.histogram, bins='auto').

Requests are checked against hard limits (memory, instrument time, detector size)
before the device is touched: invalid ones raise AcquisitionError, and device
access while a measurement is running raises Busy instead of blocking.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, replace

import numpy as np

from .backend import SpectrometerBackend, open_backend

MAX_LIVE_SCANS = 1000             # live: scans averaged per spectrum
MAX_LIVE_SECONDS = 30.0           # live averaging: scans_to_average x integration time, for 2+ scans
                                  # (a single exposure may use the device's full range)
MAX_SCANS = 5000                  # measurement: block kept as float32 (~40 MB at 2048 px)
MAX_MEASUREMENT_SECONDS = 1800.0  # measurement: num_scans x integration time
MAX_BINS = 1000                   # histogram
BIN_RULES = ("auto", "fd", "doane", "scott", "stone", "rice", "sturges", "sqrt")


class AcquisitionError(ValueError):
    """The request is invalid for the current device or configuration."""


class Busy(RuntimeError):
    """A measurement is running; the device is not available."""


@dataclass(frozen=True)
class AcquisitionConfig:
    integration_time_ms: float = 100.0
    scans_to_average: int = 1      # live: mean +- SEM over this many scans
    boxcar_width: int = 0          # live: smoothing half-width in pixels; 0 = off
    subtract_dark: bool = False    # live: subtract the dark taken at this integration time


def _mean_sem(block: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-channel mean and standard error of the mean over scans (axis 0)."""
    n = block.shape[0]
    mean = block.mean(axis=0, dtype=np.float64)
    if n < 2:
        return mean, np.zeros_like(mean)
    return mean, block.std(axis=0, ddof=1, dtype=np.float64) / np.sqrt(n)


def _boxcar(y: np.ndarray, sem: np.ndarray, half_width: int) -> tuple[np.ndarray, np.ndarray]:
    """Moving average over 2*half_width+1 pixels and the propagated SEM.

    Near the edges the window is truncated and the average is taken over the
    pixels that exist, so a flat spectrum stays flat. For uncorrelated pixels the
    SEM of a k-pixel mean is sqrt(sum sem_i^2) / k. The caller guarantees
    2*half_width+1 <= len(y), so the output has the input's length.
    """
    if half_width <= 0:
        return y, sem
    kernel = np.ones(2 * half_width + 1)
    k = np.convolve(np.ones_like(y), kernel, mode="same")
    return (np.convolve(y, kernel, mode="same") / k,
            np.sqrt(np.convolve(sem ** 2, kernel, mode="same")) / k)


def _resolve_bins(x: np.ndarray, bins: int | str) -> tuple[int | str, bool]:
    """Validate a histogram bin spec; returns (bins, capped).

    'fd' (and 'auto', which uses it) can ask for millions of bins when the
    interquartile range is tiny compared with the full range, e.g. a few outlier
    scans. Estimate that count before numpy allocates the edges.
    """
    if isinstance(bins, (int, np.integer)) and not isinstance(bins, bool):
        if not 1 <= bins <= MAX_BINS:
            raise AcquisitionError(f"bins must be between 1 and {MAX_BINS}, or one of: {', '.join(BIN_RULES)}.")
        return int(bins), False
    if bins not in BIN_RULES:
        raise AcquisitionError(
            f"Unknown bins rule {bins!r}; use a number (1-{MAX_BINS}) or one of: {', '.join(BIN_RULES)}.")
    if bins in ("fd", "auto"):
        q75, q25 = np.percentile(x, [75, 25])
        width = 2.0 * (q75 - q25) * x.size ** (-1.0 / 3.0)
        if width > 0 and float(x.max() - x.min()) / width > MAX_BINS:
            return MAX_BINS, True
    return bins, False


class AcquisitionManager:
    def __init__(self, prefer_sim: bool = False, backend: SpectrometerBackend | None = None):
        self._lock = threading.Lock()          # the device
        self._measure_lock = threading.Lock()  # one measurement at a time
        self._dev = backend if backend is not None else open_backend(prefer_sim=prefer_sim)
        self._wl = np.asarray(self._dev.wavelengths(), dtype=np.float64)
        self._cfg = AcquisitionConfig()
        self._dark: dict | None = None         # spectrum + the integration time it was taken at
        self._measurement: dict | None = None
        self._measurement_seq = 0
        self._progress = {"running": False, "done": 0, "total": 0}
        self.is_simulated = self._dev.__class__.__name__ == "SimulatedSpectrometer"
        self.fallback_reason = getattr(self._dev, "_fallback_reason", None)
        self._dev.set_integration_time_ms(self._cfg.integration_time_ms)

    # --- info -------------------------------------------------------------
    @property
    def wavelengths(self) -> np.ndarray:
        return self._wl

    @property
    def max_boxcar_width(self) -> int:
        return (self._wl.size - 1) // 2

    def info(self) -> dict:
        lo, hi = self._dev.integration_time_limits_ms
        dark = self._dark
        return {
            "model": self._dev.model,
            "serial": self._dev.serial,
            "pixels": int(self._wl.size),
            "wavelength_min_nm": float(self._wl.min()),
            "wavelength_max_nm": float(self._wl.max()),
            "integration_time_min_ms": lo,
            "integration_time_max_ms": hi,
            "saturation_counts": 2 ** 16,
            "simulated": self.is_simulated,
            "fallback_reason": self.fallback_reason,
            "has_dark": dark is not None,
            "dark_integration_time_ms": dark["integration_time_ms"] if dark else None,
            "has_measurement": self._measurement is not None,
            "limits": {
                "max_scans_to_average": MAX_LIVE_SCANS,
                "max_live_seconds": MAX_LIVE_SECONDS,
                "max_boxcar_width": self.max_boxcar_width,
                "max_scans": MAX_SCANS,
                "max_measurement_seconds": MAX_MEASUREMENT_SECONDS,
                "max_bins": MAX_BINS,
            },
        }

    def _check_idle(self) -> None:
        if self._measure_lock.locked():
            raise Busy("A measurement is running; try again when it has finished.")

    # --- config -----------------------------------------------------------
    def get_config(self) -> dict:
        return asdict(self._cfg)

    def update_config(self, **changes) -> dict:
        """Validate and apply a partial config; nothing changes if any value is invalid.

        Changing the integration time discards the dark reference (it was taken at
        the old exposure) and switches dark subtraction off; the returned
        ``notice`` says so."""
        self._check_idle()
        with self._lock:
            cur = self._cfg
            lo, hi = self._dev.integration_time_limits_ms
            it = changes.get("integration_time_ms")
            it = cur.integration_time_ms if it is None else float(it)
            if not lo <= it <= hi:
                raise AcquisitionError(f"integration_time_ms must be between {lo:g} and {hi:g} ms.")
            n = changes.get("scans_to_average")
            n = cur.scans_to_average if n is None else int(n)
            if not 1 <= n <= MAX_LIVE_SCANS:
                raise AcquisitionError(f"scans_to_average must be between 1 and {MAX_LIVE_SCANS}.")
            # The cap stops averaging from stalling the live view; it must not
            # block long single exposures, which measurements rely on.
            if n > 1 and n * it / 1000.0 > MAX_LIVE_SECONDS:
                raise AcquisitionError(
                    f"Averaging {n} scans x {it:g} ms takes {n * it / 1000.0:g} s; live averaging is limited "
                    f"to {MAX_LIVE_SECONDS:g} s. Reduce scans_to_average; for long exposures set it to 1 "
                    f"(a single exposure may use the full integration range) and use a measurement.")
            w = changes.get("boxcar_width")
            w = cur.boxcar_width if w is None else int(w)
            if not 0 <= w <= self.max_boxcar_width:
                raise AcquisitionError(f"boxcar_width must be between 0 and {self.max_boxcar_width} pixels.")

            exposure_changed = it != cur.integration_time_ms
            dark_valid = self._dark is not None and not exposure_changed
            want_dark = changes.get("subtract_dark")
            want_dark = (cur.subtract_dark and dark_valid) if want_dark is None else bool(want_dark)
            if want_dark and not dark_valid:
                raise AcquisitionError(
                    f"No dark spectrum for {it:g} ms: store one first (POST /api/dark), then enable subtract_dark.")

            new = replace(cur, integration_time_ms=it, scans_to_average=n,
                          boxcar_width=w, subtract_dark=want_dark)
            notice = None
            if exposure_changed:
                self._dev.set_integration_time_ms(it)
                if self._dark is not None:
                    self._dark = None
                    notice = "Integration time changed: dark spectrum discarded, store a new one."
            self._cfg = new
        return {**asdict(new), "notice": notice}

    # --- acquisition ------------------------------------------------------
    def _scan_block(self, n: int) -> np.ndarray:
        """``n`` raw scans as an (n, pixels) float32 array, with progress. Caller holds the lock."""
        block = np.empty((n, self._wl.size), dtype=np.float32)
        for i in range(n):
            block[i] = self._dev.intensities()
            self._progress["done"] = i + 1
        return block

    def _live_mean_sem(self, n: int) -> tuple[np.ndarray, np.ndarray]:
        """Mean and SEM over ``n`` scans without keeping them (Welford). Caller holds the lock."""
        mean = np.zeros(self._wl.size)
        m2 = np.zeros(self._wl.size)
        for k in range(1, n + 1):
            y = np.asarray(self._dev.intensities(), dtype=np.float64)
            d = y - mean
            mean += d / k
            m2 += d * (y - mean)
        if n < 2:
            return mean, np.zeros_like(mean)
        return mean, np.sqrt(m2 / (n - 1) / n)

    def acquire(self) -> dict:
        """One live spectrum: mean +- SEM over ``scans_to_average`` scans, then
        optional dark subtraction and boxcar smoothing."""
        self._check_idle()
        with self._lock:
            cfg = self._cfg
            mean, sem = self._live_mean_sem(cfg.scans_to_average)
            if cfg.subtract_dark:
                # update_config/clear_dark keep subtract_dark on only while a dark
                # taken at the current integration time exists.
                mean = mean - self._dark["spectrum"]
            mean, sem = _boxcar(mean, sem, cfg.boxcar_width)
        return {
            "timestamp": time.time(),
            "model": self._dev.model,
            "wavelengths": self._wl.tolist(),
            "intensities": mean.tolist(),
            "sem": sem.tolist(),
            "config": asdict(cfg),
        }

    def measure(self, num_scans: int) -> dict:
        """Statistical measurement as in the lab notebook: ``num_scans`` raw scans
        (no dark subtraction, no smoothing) -> per-channel mean and SEM. The scan
        block is kept so per-channel histograms can be requested afterwards.
        Only one measurement runs at a time; a second call raises Busy."""
        num_scans = int(num_scans)
        if not 2 <= num_scans <= MAX_SCANS:
            raise AcquisitionError(f"num_scans must be between 2 and {MAX_SCANS}.")
        if not self._measure_lock.acquire(blocking=False):
            raise Busy("A measurement is already running; wait for it to finish.")
        try:
            with self._lock:
                seconds = num_scans * self._cfg.integration_time_ms / 1000.0
                if seconds > MAX_MEASUREMENT_SECONDS:
                    raise AcquisitionError(
                        f"{num_scans} scans x {self._cfg.integration_time_ms:g} ms = {seconds:g} s; "
                        f"measurements are limited to {MAX_MEASUREMENT_SECONDS:g} s.")
                cfg = asdict(self._cfg)
                self._progress = {"running": True, "done": 0, "total": num_scans}
                block = self._scan_block(num_scans)
                mean, sem = _mean_sem(block)
                self._measurement_seq += 1
                m = {"id": self._measurement_seq, "timestamp": time.time(), "num_scans": num_scans,
                     "config": cfg, "block": block, "mean": mean, "sem": sem}
                self._measurement = m  # publish in one step, after the statistics exist
            return self._summary(m)
        finally:
            self._progress["running"] = False
            self._measure_lock.release()

    def _summary(self, m: dict) -> dict:
        return {
            "id": m["id"],
            "timestamp": m["timestamp"],
            "model": self._dev.model,
            "num_scans": m["num_scans"],
            "config": m["config"],
            "wavelengths": self._wl.tolist(),
            "mean": m["mean"].tolist(),
            "sem": m["sem"].tolist(),
        }

    def measurement_summary(self) -> dict | None:
        m = self._measurement
        return None if m is None else self._summary(m)

    def progress(self) -> dict:
        return dict(self._progress)

    def histogram(self, channel: int, bins: int | str = "auto") -> dict | None:
        """Intensity histogram of one channel over the scans of the last measurement."""
        m = self._measurement
        if m is None:
            return None
        if not 0 <= channel < self._wl.size:
            raise AcquisitionError(f"channel must be between 0 and {self._wl.size - 1}.")
        x = m["block"][:, channel].astype(np.float64)
        bins, capped = _resolve_bins(x, bins)
        edges = np.histogram_bin_edges(x, bins=bins)
        if edges.size - 1 > MAX_BINS:  # safety net for the other rules
            edges, capped = np.histogram_bin_edges(x, bins=MAX_BINS), True
        counts, _ = np.histogram(x, bins=edges)
        return {
            "measurement_id": m["id"],
            "channel": channel,
            "wavelength_nm": float(self._wl[channel]),
            "num_scans": m["num_scans"],
            "counts": counts.tolist(),
            "bin_edges": edges.tolist(),
            "bins_capped": capped,
            "mean": float(x.mean()),
            "std": float(x.std(ddof=1)),
            "sem": float(m["sem"][channel]),
        }

    # --- dark reference ---------------------------------------------------
    def store_dark(self) -> dict:
        """Store the mean of ``scans_to_average`` raw scans as the dark reference
        for the current integration time."""
        self._check_idle()
        with self._lock:
            spectrum, _ = self._live_mean_sem(self._cfg.scans_to_average)
            self._dark = {"spectrum": spectrum, "integration_time_ms": self._cfg.integration_time_ms,
                          "scans": self._cfg.scans_to_average, "timestamp": time.time()}
            return {"has_dark": True, "integration_time_ms": self._dark["integration_time_ms"],
                    "scans": self._dark["scans"]}

    def clear_dark(self) -> dict:
        self._check_idle()
        with self._lock:
            self._dark = None
            self._cfg = replace(self._cfg, subtract_dark=False)
        return {"has_dark": False, "subtract_dark": False}

    def close(self) -> None:
        with self._lock:
            self._dev.close()
