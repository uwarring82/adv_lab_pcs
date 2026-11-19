"""Direct HO720 USB transport; no operating-system COM port or VISA is required.

Discovery reads USB descriptors only. A selected port is claimed/configured on
Connect; identification remains the first SCPI command, handled by VisaProvider.
"""
from contextlib import suppress
from collections import deque
import hashlib
import math
import re
import sys
import time

from .backends import DeviceError, ScopeError

VID, PID = 0x0403, 0xED72
URL = "ftdi://0x0403:0xed72/1"
RESOURCE = re.compile(r"ftdi://0x0403:0xed72(?::0x[0-9a-f]{1,8}:0x[0-9a-f]{1,8})?/1", re.I)
MAX_READ = 80000


def _driver():
    try:
        import pyftdi.serialext as serialext
        from pyftdi.ftdi import Ftdi
        from pyftdi.usbtools import UsbTools
    except ImportError as exc:
        raise DeviceError("HO720 USB needs PyFtdi and libusb. Install the dashboard requirements and a libusb runtime.") from exc
    if PID not in Ftdi.PRODUCT_IDS.get(VID, {}).values():
        Ftdi.add_custom_product(VID, PID)
    if sys.platform == "win32" and "scope.usb_backend" not in UsbTools.BACKENDS:
        UsbTools.BACKENDS = ("scope.usb_backend", *UsbTools.BACKENDS)
    return serialext, Ftdi, UsbTools


def backend_status():
    """Load the native backend only; no device enumeration, claims or SCPI."""
    _, _, usb = _driver()
    try:
        backend = usb._load_backend()  # pinned PyFtdi 0.57.1 backend selection
        return type(backend).__module__
    except Exception as exc:
        raise DeviceError(f"Cannot load the HO720 USB runtime: {exc}") from exc


def resources():
    _, driver, usb = _driver()
    try:
        usb.flush_cache()  # reconnects can change the USB address
        devices = driver.list_devices(URL)
        found = set()
        for desc, interfaces in devices:
            if desc.vid != VID or desc.pid != PID or interfaces < 1:
                continue
            if desc.bus is not None and desc.address is not None:
                found.add(f"ftdi://0x0403:0xed72:0x{desc.bus:x}:0x{desc.address:x}/1")
            else:
                found.add(URL)  # PyFtdi refuses an ambiguous URL rather than picking a device
        return sorted(found)
    except Exception as exc:
        raise DeviceError(f"Cannot discover HO720 USB devices: {exc}. Check libusb and USB access permissions.") from exc


class FtdiInstrument:
    """The small VISA-like interface used by VisaScope and the byte logger."""
    def __init__(self, req):
        if not RESOURCE.fullmatch(req.resource):
            raise ScopeError("Choose a discovered HO720 USB resource or ftdi://0x0403:0xed72/1.")
        if req.flow_control == "xon_xoff":
            raise ScopeError("HO720 direct USB does not support XON/XOFF. Choose None or RTS/CTS.")
        self._serial = None
        self._events = deque(maxlen=80)
        self._started = time.monotonic()
        self._last_command = None
        self._connection = {"baud_rate": req.baud_rate, "flow_control": req.flow_control,
                            "termination": req.termination, "timeout_ms": req.timeout_ms}
        self.timeout = req.timeout_ms
        self.write_termination = {"LF": "\n", "CRLF": "\r\n", "CR": "\r"}[req.termination]
        self.read_termination = "\n"  # HO720 replies use LF for all tested outgoing endings
        serialext, _, _ = _driver()
        port = serialext.serial_for_url(req.resource, do_not_open=True, baudrate=req.baud_rate,
                                        bytesize=8, parity="N", stopbits=1, timeout=0.1,
                                        rtscts=req.flow_control == "rts_cts", xonxoff=False)
        # PyFtdi close() also runs after a failed open, when udev may not yet exist.
        port.udev = None
        try:
            port.open()
            self._serial = port
            port.ftdi.timeouts = (self.timeout, self.timeout)
            time.sleep(0.5)  # the tested HO720 can ignore an identity query sent immediately after open
            self._drain()
        except Exception as exc:
            with suppress(Exception):
                port.close()
            self._serial = None
            raise DeviceError(f"Cannot open HO720 USB: {exc}. Select USB on the scope and close other control programs.") from exc

    def write_raw(self, raw):
        self._last_command = raw.decode("ascii", "backslashreplace").strip()[:256]
        self._event("WRITE", self._last_command)
        try:
            read_timeout, _ = self._serial.ftdi.timeouts
            self._serial.ftdi.timeouts = (read_timeout, self.timeout)
            if self._serial.write(raw) != len(raw):
                raise DeviceError("Incomplete HO720 USB write. Reconnect before continuing.")
        except Exception as exc:
            self._event("WRITE_ERROR", str(exc))
            raise DeviceError(f"HO720 USB write failed for {self._last_command}: {exc}") from exc
        # PyFtdi writes submit USB data synchronously; its flush() is a no-op.
        return len(raw)

    def write(self, command):
        return self.write_raw((command + self.write_termination).encode("ascii"))

    def query(self, command):
        self.write(command)
        end = (self.read_termination or "\n").encode("ascii")
        deadline = time.monotonic() + self.timeout / 1000
        data = bytearray()
        try:
            while time.monotonic() < deadline:
                part = self._read(1, deadline)
                data.extend(part)
                if len(data) > 4096:
                    raise DeviceError(f"HO720 text reply to {command} exceeds the limit.")
                if data.endswith(end):
                    reply = data.decode("ascii").strip()
                    self._event("REPLY", f"identity ({len(data)} bytes)" if command == "*IDN?" else reply)
                    return reply
            raise TimeoutError(f"No complete LF reply to {command} from HO720 USB ({len(data)} partial bytes).")
        except Exception as exc:
            self._event("READ_ERROR", str(exc))
            raise

    def read_bytes(self, count):
        if not isinstance(count, int) or not 0 <= count <= MAX_READ:
            raise DeviceError("HO720 binary read exceeds the waveform limit.")
        deadline = time.monotonic() + self.timeout / 1000
        data = bytearray()
        try:
            while len(data) < count and time.monotonic() < deadline:
                data.extend(self._read(count - len(data), deadline))
            if len(data) != count:
                raise TimeoutError(f"HO720 USB returned {len(data)} of {count} binary bytes.")
        except Exception as exc:
            self._event("READ_ERROR", str(exc))
            raise
        self._event("BINARY", f"{count} bytes; " + (data.hex(" ") if count <= 16 else hashlib.sha256(data).hexdigest()))
        return bytes(data)

    def _event(self, phase, detail):
        self._events.append({"elapsed_s": round(time.monotonic() - self._started, 3),
                             "phase": phase, "detail": detail[:512]})

    @property
    def diagnostics(self):
        """Cached data only: reading this property performs no USB operation."""
        return {"transport": "HO720 USB", "connection": dict(self._connection), "last_command": self._last_command,
                "events": [dict(event) for event in self._events]}

    def _read(self, count, deadline):
        # Match the 100 ms polling used by the successful hardware checker.
        # Changing serial.timeout while open reconfigures the UART, so keep it
        # fixed and bound the underlying USB operation here instead.
        from usb.core import USBError, USBTimeoutError
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return b""
        self._serial.ftdi.timeouts = (max(1, math.ceil(remaining * 1000)), self.timeout)
        try:
            # Pinned PyFtdi 0.57.1 may discard an accumulated result if a later
            # USB packet times out. A read wholly inside its cache cannot issue
            # USB I/O; otherwise fetch only one byte so no prefix can be lost.
            # Fall back to single-byte reads if these cache fields are absent.
            driver = self._serial.ftdi
            available = len(getattr(driver, "_readbuffer", b"")) - getattr(driver, "_readoffset", 0)
            return self._serial.read(min(count, max(1, available)))
        except Exception as exc:
            pending, seen = [exc], set()
            while pending:
                cause = pending.pop()
                if id(cause) in seen:
                    continue
                seen.add(id(cause))
                if isinstance(cause, USBTimeoutError) or (isinstance(cause, USBError) and (
                        cause.errno in (60, 110) or cause.backend_error_code == -7)):
                    self._event("USB_READ_TIMEOUT", str(cause))
                    return b""
                pending.extend(e for e in (cause.__cause__, cause.__context__) if e is not None)
            raise

    def flush(self, mask):
        self._drain()

    def clear(self):
        self._drain()

    def _drain(self):
        # Match the successful checker: read old bytes through one quiet poll.
        # A hardware purge/reset between SCPI requests is not needed here.
        deadline, count = time.monotonic() + 1, 0
        while time.monotonic() < deadline:
            part = self._read(1, deadline)
            if not part:
                self._event("DRAIN", f"{count} old bytes consumed; quiet")
                return
            count += len(part)
        self._event("DRAIN_ERROR", f"{count} bytes; continuous input")
        raise DeviceError("HO720 USB input did not become quiet before the next command.")

    def close(self):
        port, self._serial = self._serial, None
        if port is not None:
            try:
                port.close()
            finally:
                self._event("CLOSE", "USB port close attempted")
