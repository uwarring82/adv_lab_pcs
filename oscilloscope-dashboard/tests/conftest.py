"""Offline suite: forbid real USB discovery/claim even when a scope is attached."""
import pytest
from pyftdi.ftdi import Ftdi
from pyftdi.usbtools import UsbTools


@pytest.fixture(autouse=True)
def no_real_ftdi_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must replace USB discovery and device creation")
    monkeypatch.setattr(Ftdi, "create_from_url", forbidden)
    monkeypatch.setattr(UsbTools, "find_all", forbidden)
