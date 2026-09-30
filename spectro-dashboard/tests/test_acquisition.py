"""Regression tests for the acquisition layer (no hardware, no integration-time sleeps)."""
import threading

import numpy as np
import pytest

from spectro.acquisition import (
    MAX_BINS, MAX_LIVE_SCANS, MAX_SCANS, AcquisitionError, AcquisitionManager, Busy)
from spectro.backend.base import SpectrometerBackend
from spectro.backend.sim_backend import SimulatedSpectrometer


class SequenceBackend(SpectrometerBackend):
    """Replays the given scans in a cycle: deterministic data for statistics tests."""

    def __init__(self, scans):
        self.model, self.serial = "Sequence", None
        self._scans = [np.asarray(s, dtype=float) for s in scans]
        self._i = 0

    def wavelengths(self):
        return np.linspace(340.0, 1025.0, self._scans[0].size)

    def intensities(self):
        s = self._scans[self._i % len(self._scans)]
        self._i += 1
        return s

    def set_integration_time_ms(self, ms):
        pass

    @property
    def integration_time_limits_ms(self):
        return (1.0, 65000.0)


class GatedBackend(SequenceBackend):
    """Blocks every scan until ``release`` is set, so a measurement stays in progress."""

    def __init__(self, scans):
        super().__init__(scans)
        self.started = threading.Event()
        self.release = threading.Event()

    def intensities(self):
        self.started.set()
        self.release.wait(5)
        return super().intensities()


def sim_manager() -> AcquisitionManager:
    return AcquisitionManager(backend=SimulatedSpectrometer(seed=0, realtime=False))


# --- live averaging limits (review finding 1) -----------------------------------
def test_live_averaging_is_bounded_and_rejections_change_nothing():
    m = sim_manager()
    with pytest.raises(AcquisitionError):
        m.update_config(scans_to_average=1_000_000)
    with pytest.raises(AcquisitionError):
        m.update_config(scans_to_average=MAX_LIVE_SCANS + 1)
    with pytest.raises(AcquisitionError):  # 31 x 1 s > 30 s
        m.update_config(integration_time_ms=1000, scans_to_average=31)
    assert m.get_config()["scans_to_average"] == 1
    assert m.get_config()["integration_time_ms"] == 100

    m.update_config(scans_to_average=300)  # 300 x 100 ms = 30 s: allowed
    with pytest.raises(AcquisitionError):  # longer exposure pushes it to 60 s
        m.update_config(integration_time_ms=200)
    assert m.get_config()["integration_time_ms"] == 100


def test_long_single_exposure_is_allowed_for_measurements():
    m = sim_manager()
    m.update_config(integration_time_ms=31_000)  # one 31 s exposure: allowed
    assert m.measure(2)["config"]["integration_time_ms"] == 31_000  # 62 s measurement
    with pytest.raises(AcquisitionError):  # but averaging it live would take 62 s
        m.update_config(scans_to_average=2)
    m.update_config(integration_time_ms=65_000)  # the device maximum
    with pytest.raises(AcquisitionError):
        m.update_config(integration_time_ms=65_001)


def test_live_mean_and_sem_match_numpy():
    scans = np.random.default_rng(1).poisson(1000, size=(7, 64)).astype(float)
    m = AcquisitionManager(backend=SequenceBackend(scans))
    m.update_config(scans_to_average=7)
    s = m.acquire()
    np.testing.assert_allclose(s["intensities"], scans.mean(axis=0))
    np.testing.assert_allclose(s["sem"], scans.std(axis=0, ddof=1) / np.sqrt(7))


# --- boxcar (review finding 3) ----------------------------------------------------
@pytest.mark.parametrize("width", [0, 1, 7, 1023])
def test_boxcar_keeps_spectrum_length(width):
    m = sim_manager()
    m.update_config(boxcar_width=width)
    s = m.acquire()
    assert len(s["wavelengths"]) == len(s["intensities"]) == len(s["sem"]) == 2048


def test_boxcar_wider_than_detector_is_rejected():
    m = sim_manager()
    with pytest.raises(AcquisitionError):
        m.update_config(boxcar_width=1024)
    assert m.get_config()["boxcar_width"] == 0


def test_boxcar_keeps_flat_spectrum_flat_and_propagates_sem():
    flat = np.full(64, 500.0)
    m = AcquisitionManager(backend=SequenceBackend([flat, flat + 2]))  # mean 501, SEM 1
    m.update_config(scans_to_average=2, boxcar_width=3)
    s = m.acquire()
    np.testing.assert_allclose(s["intensities"], 501.0)  # no darkening at the edges
    sem = np.array(s["sem"])
    np.testing.assert_allclose(sem[3:-3], 1 / np.sqrt(7))  # full 7-pixel window
    assert sem[0] == pytest.approx(1 / np.sqrt(4))          # truncated 4-pixel window


# --- measurements (review finding 4) -----------------------------------------------
def test_concurrent_measurement_is_rejected_and_result_not_overwritten():
    dev = GatedBackend([np.full(16, 10.0), np.full(16, 12.0)])
    m = AcquisitionManager(backend=dev)
    result = {}
    t = threading.Thread(target=lambda: result.update(first=m.measure(4)))
    t.start()
    try:
        assert dev.started.wait(5)
        assert m.progress()["running"] is True
        with pytest.raises(Busy):
            m.measure(2)
        with pytest.raises(Busy):  # device calls fail fast instead of blocking
            m.acquire()
        with pytest.raises(Busy):
            m.update_config(integration_time_ms=50)
    finally:
        dev.release.set()
        t.join(5)
    first = result["first"]
    assert first["id"] == 1 == m.measurement_summary()["id"]
    assert m.progress() == {"running": False, "done": 4, "total": 4}
    second = m.measure(2)
    assert second["id"] == 2 == m.measurement_summary()["id"]


def test_measurement_limits():
    m = sim_manager()
    with pytest.raises(AcquisitionError):
        m.measure(1)
    with pytest.raises(AcquisitionError):
        m.measure(MAX_SCANS + 1)
    m.update_config(integration_time_ms=1000)
    with pytest.raises(AcquisitionError):  # 1801 s > 30 min
        m.measure(1801)
    assert m.progress()["running"] is False
    assert m.measurement_summary() is None


def test_measurement_statistics():
    scans = np.random.default_rng(2).poisson(500, size=(40, 32)).astype(float)
    m = AcquisitionManager(backend=SequenceBackend(scans))
    r = m.measure(40)
    np.testing.assert_allclose(r["mean"], scans.mean(axis=0), rtol=1e-6)
    np.testing.assert_allclose(r["sem"], scans.std(axis=0, ddof=1) / np.sqrt(40), rtol=1e-5)


# --- dark reference (review finding 5) ----------------------------------------------
def test_dark_is_discarded_when_integration_time_changes():
    m = sim_manager()
    m.store_dark()
    assert m.update_config(subtract_dark=True)["subtract_dark"] is True
    cfg = m.update_config(integration_time_ms=200)
    assert cfg["subtract_dark"] is False and cfg["notice"]
    assert m.info()["has_dark"] is False
    with pytest.raises(AcquisitionError):
        m.update_config(subtract_dark=True)

    m.store_dark()
    assert m.info()["dark_integration_time_ms"] == 200
    with pytest.raises(AcquisitionError):  # new exposure + subtract in one call: rejected as a whole
        m.update_config(integration_time_ms=300, subtract_dark=True)
    assert m.info()["has_dark"] is True and m.get_config()["integration_time_ms"] == 200

    assert m.update_config(integration_time_ms=200, subtract_dark=True)["notice"] is None  # same exposure
    assert m.acquire()["config"]["subtract_dark"] is True


def test_clear_dark_switches_subtraction_off():
    m = sim_manager()
    m.store_dark()
    m.update_config(subtract_dark=True)
    m.clear_dark()
    assert m.get_config()["subtract_dark"] is False


# --- histograms (review finding 6) --------------------------------------------------
def test_histogram_rejects_invalid_parameters():
    m = sim_manager()
    assert m.histogram(600) is None  # no measurement yet
    m.measure(50)
    for bad in (0, -1, MAX_BINS + 1, 10 ** 9, "bogus", True):
        with pytest.raises(AcquisitionError):
            m.histogram(600, bad)
    for channel in (-1, 2048):
        with pytest.raises(AcquisitionError):
            m.histogram(channel)
    h = m.histogram(600, "auto")
    assert sum(h["counts"]) == 50 and len(h["bin_edges"]) == len(h["counts"]) + 1
    assert h["bins_capped"] is False
    assert len(m.histogram(600, 20)["counts"]) == 20


def test_histogram_bin_count_is_capped_for_outliers():
    # 3750 scans at 1000, 1249 at 1001, one at 65535: IQR 0.25 against a range of
    # 64535, so 'fd'/'auto' would ask numpy for about 2.2 million bins.
    scans = [np.full(8, 1000.0)] * 3750 + [np.full(8, 1001.0)] * 1249 + [np.full(8, 65535.0)]
    m = AcquisitionManager(backend=SequenceBackend(scans))
    m.measure(5000)
    for rule in ("auto", "fd"):
        h = m.histogram(3, rule)
        assert h["bins_capped"] is True
        assert len(h["counts"]) == MAX_BINS and sum(h["counts"]) == 5000
