"""Windows libusb loader used by PyFtdi; loading does not claim an instrument."""
from pathlib import Path
import sys


def find_library(candidate):
    if getattr(sys, "frozen", False) and candidate in ("usb-1.0", "libusb-1.0", "usb", "libusb"):
        # An adjacent replacement DLL takes precedence over the bundled runtime.
        # PyInstaller's libusb-package hook places the bundled DLL at this root.
        for directory in (Path(sys.executable).parent, Path(sys._MEIPASS)):
            dll = directory / "libusb-1.0.dll"
            if dll.is_file():
                return str(dll)
    from libusb_package import find_library as packaged_library
    return packaged_library(candidate)


def get_backend():
    from usb.backend import libusb1
    return libusb1.get_backend(find_library=find_library)
