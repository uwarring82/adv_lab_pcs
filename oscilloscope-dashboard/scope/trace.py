"""Serial/VISA exchange log and the one-button HMO diagnosis (rc5).

The log is plain text, one line per event: ISO time with milliseconds, direction (TX = sent,
RX = received, ERR = failure) and the data as text and hex. It contains no personal data; it is
meant to be sent back by a lab user when an instrument times out.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path


def log_dir():
    return Path.home() / "oscilloscope-dashboard-logs"


def stamp():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def show(data):
    raw = data.encode("latin-1", "replace") if isinstance(data, str) else bytes(data)
    text = raw.decode("latin-1").encode("unicode_escape").decode("ascii")
    return f"{text!r:<40} hex={raw.hex(' ')} ({len(raw)} bytes)"


class TraceLog:
    def __init__(self, directory=None, prefix="serial-log"):
        directory = Path(directory) if directory else log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{prefix}-{datetime.now():%Y%m%d-%H%M%S}.txt"
        self.start = time.monotonic()

    def line(self, kind, text=""):
        elapsed = time.monotonic() - self.start
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp()} +{elapsed:8.3f}s {kind:<4} {text}\n")

    def note(self, text):
        self.line("NOTE", text)


class TracedInstrument:
    """Wraps a PyVISA resource: logs every exchange, forwards everything else unchanged."""

    def __init__(self, instrument, log):
        object.__setattr__(self, "_inst", instrument)
        object.__setattr__(self, "_log", log)

    def __getattr__(self, name):
        return getattr(self._inst, name)

    def __setattr__(self, name, value):
        setattr(self._inst, name, value)

    def write(self, command):
        self._log.line("TX", show(command + (self._inst.write_termination or "")))
        return self._inst.write(command)

    def query(self, command):
        self._log.line("TX", show(command + (self._inst.write_termination or "")))
        try:
            reply = self._inst.query(command)
        except Exception as exc:
            try:
                waiting = self._inst.bytes_in_buffer
            except Exception:
                waiting = "unknown"
            self._log.line("ERR", f"query {command!r}: {exc}; bytes waiting in receive buffer: {waiting}")
            raise
        self._log.line("RX", show(reply + (self._inst.read_termination or "")))
        return reply

    def read_bytes(self, count):
        try:
            data = self._inst.read_bytes(count)
        except Exception as exc:
            self._log.line("ERR", f"read_bytes({count}): {exc}")
            raise
        self._log.line("RX", f"{len(data)} bytes" if count > 16 else show(data))
        return data

    def clear(self):
        self._log.line("NOTE", "clear()")
        return self._inst.clear()

    def flush(self, mask):
        self._log.line("NOTE", f"flush({mask})")
        return self._inst.flush(mask)


def header(log, resource, req, visa_info):
    from . import __version__
    log.note(f"oscilloscope-dashboard {__version__}; {visa_info}")
    log.note(f"resource={resource} baud={req.baud_rate} 8N1 flow={req.flow_control} "
             f"termination={req.termination} timeout={req.timeout_ms} ms")


def read_raw(inst, log, wait_s):
    """Read byte by byte until LF or `wait_s` without a new byte; log every byte with its time."""
    got, deadline = bytearray(), time.monotonic() + wait_s
    previous = inst.timeout
    inst.timeout = 100
    try:
        while time.monotonic() < deadline:
            try:
                byte = inst.read_bytes(1)
            except Exception:
                continue
            got += byte
            log.line("RXB", show(byte))
            deadline = time.monotonic() + wait_s
            if byte == b"\n":
                break
    finally:
        inst.timeout = previous
    return bytes(got)


def discard_input(inst, log=None):
    """Drop unread bytes in the VISA receive buffer (stale or late replies)."""
    try:
        from pyvisa import constants
        inst.flush(constants.BufferOperation.discard_read_buffer)
    except Exception as exc:
        if log:
            log.note(f"flush not possible: {exc}")


STEPS = [("*IDN?", True), (":TIM:SCAL?", True), (":TIMebase:SCALe?", True), (":SYST:ERR?", True),
         ("*CLS", False), (":TIM:SCAL?", True), ("*OPC?", True), (":CHAN1:SCAL?", True)]


def diagnose(inst, log, wait_s=2.0, pause_s=0.5):
    """Send a fixed, read-only query sequence and record what comes back byte by byte.

    Returns a list of {command, reply, ok}. `*CLS` only clears the instrument's status/error queue.
    """
    results = []
    term = inst.write_termination or "\n"
    for command, is_query in STEPS:
        log.note(f"step {len(results) + 1}: {command}")
        discard_input(inst, log)
        log.line("TX", show(command + term))
        inst.write_raw((command + term).encode("ascii"))
        reply = read_raw(inst, log, wait_s) if is_query else b""
        ok = bool(reply) if is_query else True
        log.note(f"result: {'reply ' + repr(reply.decode('latin-1')) if reply else ('no reply' if is_query else 'sent')}")
        results.append({"command": command, "reply": reply.decode("latin-1").strip(), "ok": ok})
        time.sleep(pause_s)
        late = read_raw(inst, log, 0.3) if not ok else b""
        if late:
            log.note(f"late bytes after {command}: {late!r}")
        if command == "*IDN?" and not reply:
            log.note("no reply to *IDN?: stopping (check baud rate, cable, line ending, remote interface)")
            break
    return results
