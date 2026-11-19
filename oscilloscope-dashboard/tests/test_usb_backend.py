from pathlib import Path
from types import SimpleNamespace
import sys

from scope import ftdi, usb_backend
from pyftdi.usbtools import UsbTools


def test_source_library_uses_packaged_lookup(monkeypatch):
    monkeypatch.setitem(sys.modules,'libusb_package',SimpleNamespace(find_library=lambda name:'packaged/'+name))
    monkeypatch.delattr(usb_backend.sys,'frozen',raising=False)
    assert usb_backend.find_library('usb-1.0') == 'packaged/usb-1.0'


def test_frozen_runtime_prefers_replaceable_adjacent_dll(tmp_path,monkeypatch):
    exe=tmp_path/'application';exe.mkdir()
    bundled=tmp_path/'bundle';bundled.mkdir()
    monkeypatch.setattr(usb_backend.sys,'frozen',True,raising=False)
    monkeypatch.setattr(usb_backend.sys,'executable',str(exe/'OscilloscopeDashboard.exe'))
    monkeypatch.setattr(usb_backend.sys,'_MEIPASS',str(bundled),raising=False)
    (bundled/'libusb-1.0.dll').write_bytes(b'bundled')
    assert Path(usb_backend.find_library('usb-1.0')) == bundled/'libusb-1.0.dll'
    (exe/'libusb-1.0.dll').write_bytes(b'replacement')
    assert Path(usb_backend.find_library('usb-1.0')) == exe/'libusb-1.0.dll'


def test_windows_backend_registration_is_idempotent(monkeypatch):
    monkeypatch.setattr(ftdi.sys,'platform','win32')
    monkeypatch.setattr(UsbTools,'BACKENDS',('usb.backend.libusb1',))
    ftdi._driver();ftdi._driver()
    assert UsbTools.BACKENDS == ('scope.usb_backend','usb.backend.libusb1')


def test_packaged_backend_supplies_library_finder(monkeypatch):
    from usb.backend import libusb1
    called=[]
    monkeypatch.setattr(libusb1,'get_backend',lambda **kw:called.append(kw) or 'backend')
    assert usb_backend.get_backend() == 'backend'
    assert called == [{'find_library':usb_backend.find_library}]


def test_cli_runtime_check_never_starts_server_or_discovers_devices(monkeypatch,capsys):
    import run
    monkeypatch.setattr(sys,'argv',['run.py','--check-usb-backend'])
    monkeypatch.setattr(ftdi,'backend_status',lambda:'usb.backend.libusb1')
    monkeypatch.setattr(run,'create_app',lambda *args:(_ for _ in ()).throw(AssertionError('no server')))
    run.main()
    assert 'HO720 USB runtime:' in capsys.readouterr().out
