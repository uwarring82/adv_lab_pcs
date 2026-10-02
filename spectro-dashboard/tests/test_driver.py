"""Driver installation logic (the elevated pnputil step itself needs Windows + a device)."""
import hashlib
import io
import zipfile

import pytest

from spectro import driver
from spectro.driver import DriverError, devices_needing_driver, hardware_id, matching_infs


def test_hardware_id_from_instance_id():
    assert hardware_id(r"USB\VID_2457&PID_101E\5&1730C901&0&1") == "VID_2457&PID_101E"
    assert hardware_id("ACPI\\PNP0A08") is None


def test_devices_needing_driver():
    ok = {"status": "OK", "service": "WinUSB", "instance_id": r"USB\VID_2457&PID_101E\1"}
    no_driver = {"status": "Error", "service": None, "instance_id": r"USB\VID_2457&PID_101E\2"}
    jungo = {"status": "OK", "service": "windrvr6", "instance_id": r"USB\VID_2457&PID_1022\3"}
    assert devices_needing_driver([ok, no_driver, jungo]) == [no_driver, jungo]
    assert devices_needing_driver(None) == [] and devices_needing_driver({"error": "x"}) == []


def test_matching_infs_picks_the_device_and_skips_xp(tmp_path):
    (tmp_path / "OOI_USB2000Plus.inf").write_text("%Desc% = OOIUSB_Install, USB\\VID_2457&PID_101E\n")
    (tmp_path / "OOI_USB2000Plus_XP.inf").write_text("USB\\VID_2457&PID_101E\n")
    (tmp_path / "OOI_USB4000.inf").write_text("USB\\VID_2457&PID_1022\n")
    assert [p.name for p in matching_infs(tmp_path, ["VID_2457&PID_101E"])] == ["OOI_USB2000Plus.inf"]


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_checks_checksum_and_paths(tmp_path, monkeypatch):
    good = _zip({"OOI_USB2000Plus.inf": "USB\\VID_2457&PID_101E"})
    monkeypatch.setattr(driver.urllib.request, "urlopen", lambda url, timeout: _Response(good))
    folder = driver.download_package(tmp_path / "ok", sha256=hashlib.sha256(good).hexdigest())
    assert (folder / "OOI_USB2000Plus.inf").exists()

    with pytest.raises(DriverError, match="checksum"):
        driver.download_package(tmp_path / "bad", sha256="0" * 64)

    evil = _zip({"../escape.inf": "x"})
    monkeypatch.setattr(driver.urllib.request, "urlopen", lambda url, timeout: _Response(evil))
    with pytest.raises(DriverError, match="Unsafe"):
        driver.download_package(tmp_path / "evil", sha256=hashlib.sha256(evil).hexdigest())
    assert not (tmp_path / "escape.inf").exists()


def test_install_refuses_off_windows_or_without_device(monkeypatch):
    monkeypatch.setattr(driver.sys, "platform", "darwin")
    with pytest.raises(DriverError, match="only possible on Windows"):
        driver.install([])
    monkeypatch.setattr(driver.sys, "platform", "win32")
    with pytest.raises(DriverError, match="No connected Ocean Optics device"):
        driver.install([{"status": "OK", "service": "WinUSB", "instance_id": r"USB\VID_2457&PID_101E\1"}])
