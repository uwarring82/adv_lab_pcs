"""Wavelength calibration and dark subtraction with uncertainties (no hardware)."""
import numpy as np
import pytest

from spectro.acquisition import AcquisitionManager
from spectro.calibration import (
    CalibrationError, CalibrationStore, check_coefficients, compare, evaluate,
    factory_coefficients, fit_lines)
from tests.test_acquisition import SequenceBackend

N = 2048
TRUE = [339.4, 0.3846, -1.71e-5, 2.1e-10]  # a USB2000+-like polynomial


class PolyBackend(SequenceBackend):
    """Flat spectra with wavelengths from a given polynomial, like the device EEPROM."""

    def __init__(self, scans, coefficients=TRUE, serial="FLMS00001"):
        super().__init__(scans)
        self.model, self.serial = "USB2000PLUS", serial
        self._coefficients = coefficients

    def wavelengths(self):
        return evaluate(self._coefficients, np.arange(N))


def manager(tmp_path=None, scans=None):
    store = CalibrationStore(tmp_path / "cal.json" if tmp_path else None)
    return AcquisitionManager(backend=PolyBackend(scans or [np.full(N, 1000.0)]), calibration_store=store)


# --- polynomial helpers ------------------------------------------------------------
def test_factory_coefficients_recover_the_device_polynomial():
    np.testing.assert_allclose(factory_coefficients(evaluate(TRUE, np.arange(N))), TRUE, rtol=1e-6)


def test_factory_coefficients_of_a_linear_axis_have_clean_zeros():
    assert factory_coefficients(np.linspace(340.0, 1025.0, N))[2:] == [0.0, 0.0]


def test_fit_through_exact_lines_recovers_polynomial():
    pixels = [100.3, 600.0, 1200.7, 1900.2]
    fit = fit_lines([(p, float(evaluate(TRUE, p))) for p in pixels], N, order=3)
    np.testing.assert_allclose(fit["coefficients"], TRUE, rtol=1e-6)


@pytest.mark.parametrize("lines, order, message", [
    ([(100, 400.0)], None, "At least 2"),
    ([(100, 400.0), (100, 500.0)], None, "different pixel"),
    ([(100, 400.0), (5000, 500.0)], None, "between 0 and"),
    ([(100, 400.0), (200, 500.0)], 2, "needs at least 3"),
    ([(100, 500.0), (200, 400.0)], None, "increasing"),
])
def test_fit_rejects_bad_lines(lines, order, message):
    with pytest.raises(CalibrationError, match=message):
        fit_lines(lines, N, order)


def test_coefficients_must_increase_and_be_finite():
    assert check_coefficients([340, 0.33], N) == [340.0, 0.33, 0.0, 0.0]
    for bad in ([], [340, -0.1], [340, float("nan")], [1, 2, 3, 4, 5]):
        with pytest.raises(CalibrationError):
            check_coefficients(bad, N)


def test_comparison_shows_both_calibrations_per_line():
    factory = list(TRUE)
    custom = [TRUE[0] + 0.5, *TRUE[1:]]                 # custom shifted by +0.5 nm
    lines = [{"pixel": 600.0, "wavelength_nm": float(evaluate(TRUE, 600.0)) + 0.5}]
    c = compare(factory, custom, lines, N)
    row = c["lines"][0]
    assert row["factory_residual_nm"] == pytest.approx(-0.5)
    assert row["custom_residual_nm"] == pytest.approx(0.0, abs=1e-9)
    assert c["max_difference_nm"] == pytest.approx(0.5)
    assert c["factory_rms_nm"] == pytest.approx(0.5) and c["custom_rms_nm"] == pytest.approx(0.0, abs=1e-9)


# --- manager: apply, persist, reset ------------------------------------------------
def test_custom_calibration_changes_wavelengths_and_is_saved_per_device(tmp_path):
    m = manager(tmp_path)
    assert m.calibration_info()["active"] == "factory"
    lines = [{"pixel": p, "wavelength_nm": float(evaluate(TRUE, p)) + 1.0} for p in (200, 900, 1700)]
    info = m.set_calibration(lines=lines, order=2)
    assert info["active"] == "custom" and info["source"] == "fit" and info["save_error"] is None
    assert m.acquire()["wavelengths"][900] == pytest.approx(float(evaluate(TRUE, 900)) + 1.0, abs=0.05)
    assert m.info()["calibration"] == "custom"

    again = manager(tmp_path)                                    # restart: loaded from file
    assert again.calibration_info()["active"] == "custom"
    other = AcquisitionManager(backend=PolyBackend([np.full(N, 1.0)], serial="OTHER"),
                               calibration_store=CalibrationStore(tmp_path / "cal.json"))
    assert other.calibration_info()["active"] == "factory"      # another device: factory

    reset = again.reset_calibration()
    assert reset["active"] == "factory"
    assert manager(tmp_path).calibration_info()["active"] == "factory"


def test_entered_coefficients_keep_lines_for_comparison():
    m = manager()
    info = m.set_calibration(coefficients=[340.0, 0.33],
                             lines=[{"pixel": 500.0, "wavelength_nm": 505.0}])
    assert info["source"] == "coefficients" and info["order"] == 1
    assert info["comparison"]["lines"][0]["custom_nm"] == pytest.approx(505.0)


def test_corrupt_saved_calibration_falls_back_to_factory(tmp_path):
    (tmp_path / "cal.json").write_text('{"USB2000PLUS:FLMS00001": {"coefficients": [1000, -1]}}')
    assert manager(tmp_path).calibration_info()["active"] == "factory"


# --- dark subtraction with uncertainties ----------------------------------------
def test_dark_sem_adds_in_quadrature_live_and_in_measurements():
    signal = [np.full(N, 1010.0), np.full(N, 1030.0)]   # mean 1020, SEM 10
    m = AcquisitionManager(backend=PolyBackend(signal))
    m.update_config(scans_to_average=2)
    m.store_dark()                                          # dark: same scans -> mean 1020, SEM 10
    m.update_config(subtract_dark=True)
    s = m.acquire()
    assert s["intensities"][0] == pytest.approx(0.0)
    assert s["sem"][0] == pytest.approx(np.sqrt(2) * 10)

    r = m.measure(4)                                        # 1010, 1030, 1010, 1030
    assert r["dark_subtracted"] is True and r["dark_scans"] == 2
    assert r["mean"][0] == pytest.approx(0.0) and r["raw_mean"][0] == pytest.approx(1020.0)
    raw_sem = np.std([1010, 1030, 1010, 1030], ddof=1) / 2
    assert r["sem"][0] == pytest.approx(np.hypot(raw_sem, 10))
    h = m.histogram(0)                                      # histograms stay raw counts
    assert h["mean"] == pytest.approx(1020.0) and h["sem"] == pytest.approx(raw_sem)


def test_measurement_without_dark_has_no_extra_fields():
    r = manager().measure(2)
    assert r["dark_subtracted"] is False and "raw_mean" not in r
