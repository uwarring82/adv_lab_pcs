"""Diagnostics hints and reconnecting, without hardware."""
import threading

import numpy as np
import pytest

from spectro.acquisition import AcquisitionManager, Busy
from spectro.backend.sim_backend import SimulatedSpectrometer
from spectro.diagnostics import hints
from tests.test_acquisition import GatedBackend, SequenceBackend

NOT_FOUND = "No Ocean Optics spectrometer found."


def report(usb, seabreeze=None, frozen=True, **spec):
    base = {"simulated": True, "forced_simulator": False, "model": "Simulated USB2000+",
            "serial": None, "fallback_reason": NOT_FOUND}
    base.update(spec)
    sb = {"version": "2.10.1", "backend": "cseabreeze", "backend_messages": [], "devices": [],
          "error": None}
    sb.update(seabreeze or {})
    return {"frozen": frozen, "spectrometer": base, "seabreeze": sb, "usb_devices": usb}


def device(**kw):
    d = {"name": "USB2000+", "status": "OK", "class": "OceanOpticsUSBDevice",
         "instance_id": r"USB\VID_2457&PID_101E\1", "service": "WinUSB",
         "driver_provider": "Ocean Optics", "driver_version": "2.0", "inf": "oem12.inf"}
    d.update(kw)
    return d


def joined(r):
    return " ".join(hints(r))


def test_hardware_in_use_and_forced_simulator():
    assert "Nothing to fix" in joined(report([], simulated=False, model="USB2000PLUS"))
    assert "--sim" in joined(report([], forced_simulator=True))


def test_windows_sees_no_device():
    text = joined(report([]))
    assert "does not see any Ocean Optics USB device" in text and "0999" in text


def test_wrong_driver_is_named():
    text = joined(report([device(service="windrvr6", driver_provider="Jungo")]))
    assert "windrvr6" in text and "Jungo" in text and "Install driver" in text


def test_driver_problem_status():
    # Maxim's lab PC: Windows knows the name, but there is no driver (Code 28)
    text = joined(report([device(status="Error", service=None, driver_provider=None, inf=None)]))
    assert "status 'Error'" in text and "Install driver" in text


def test_winusb_but_seabreeze_sees_nothing():
    text = joined(report([device()]))
    assert "WinUSB driver, but seabreeze does not find it" in text and "Retry hardware" in text


def test_device_seen_but_busy():
    r = report([device()], seabreeze={"devices": ["<SeaBreezeDevice USB2000PLUS:FLMS1>"]},
               fallback_reason="device is already open")
    text = joined(r)
    assert "could not open it" in text and "OceanView" in text


def test_backend_import_failure_frozen_vs_source():
    failed = {"backend": None, "error": "ImportError: DLL load failed"}
    assert "problem of the app itself" in joined(report([], seabreeze=failed, frozen=True))
    assert "pip install seabreeze" in joined(report(None, seabreeze=failed, frozen=False))


def test_fallback_to_pyseabreeze_is_reported():
    assert "pyseabreeze" in joined(report([], seabreeze={"backend": "pyseabreeze"}))


def test_usb_query_error_is_reported():
    assert "Could not ask Windows" in joined(report({"error": "timeout"}))


# --- reconnect -----------------------------------------------------------------------
def still_missing(prefer_sim=False):
    sim = SimulatedSpectrometer(realtime=False)
    sim._fallback_reason = "still not there"
    return sim


def test_reconnect_without_hardware_keeps_simulator():
    m = AcquisitionManager(opener=still_missing)
    assert m.reconnect() == {"connected": False, "reason": "still not there"}
    assert m.info()["simulated"] is True and m.info()["fallback_reason"] == "still not there"


def test_reconnect_switches_to_hardware_and_resets_state():
    scans = [np.full(64, 100.0)]
    m = AcquisitionManager(opener=still_missing)
    m.update_config(integration_time_ms=50, scans_to_average=3)
    m.store_dark()
    m.measure(2)
    m._opener = lambda prefer_sim=False: SequenceBackend(scans)
    r = m.reconnect()
    assert r["connected"] is True and r["model"] == "Sequence"
    info = m.info()
    assert info["simulated"] is False and info["fallback_reason"] is None and info["pixels"] == 64
    assert info["has_dark"] is False and info["has_measurement"] is False
    assert m.get_config()["scans_to_average"] == 1
    assert len(m.acquire()["intensities"]) == 64
    assert m.reconnect()["connected"] is True  # already on hardware: no reopening


def test_reconnect_is_rejected_during_a_measurement():
    dev = GatedBackend([np.full(16, 1.0)])
    m = AcquisitionManager(backend=dev)
    t = threading.Thread(target=lambda: m.measure(3))
    t.start()
    try:
        assert dev.started.wait(5)
        with pytest.raises(Busy):
            m.reconnect()
    finally:
        dev.release.set()
        t.join(5)
