"""Model-specific SCPI drivers. Protocol references and limits are in README.md."""
from __future__ import annotations

import math
import re
from contextlib import suppress

import numpy as np

from .models import Connection, Settings

MAX_POINTS = 20000
PROFILES = {
    "DS1054Z": ("rigol", 4), "DS1074Z": ("rigol", 4),
    "DS1104Z": ("rigol", 4), "DS1202Z-E": ("rigol", 2),
    "HMO1022": ("hmo", 2), "HMO3524": ("hmo", 4),
}


class ScopeError(Exception):
    status_code = 422


class DeviceError(ScopeError):
    status_code = 503


class Busy(ScopeError):
    status_code = 409


def identify(identity):
    fields = [x.strip() for x in identity.split(",")]
    if len(fields) < 3:
        raise ScopeError(f"Unrecognised identification response: {identity!r}")
    vendor, model, serial = fields[:3]
    key = model.upper().replace(" ", "")
    # DS1000Z Plus has the same analog command set.
    key = key.removesuffix("PLUS")
    profile = PROFILES.get(key)
    vendor_ok = profile and (
        (profile[0] == "rigol" and "RIGOL" in vendor.upper()) or
        (profile[0] == "hmo" and any(v in vendor.upper() for v in ("HAMEG", "ROHDE", "R&S"))))
    if not vendor_ok:
        raise ScopeError(f"No verified driver for {vendor} {model}. HM1508/HM1508-2 and the inventory's "
                         "HM1022 entry need protocol/model confirmation; no control commands were sent.")
    return {"vendor": vendor, "model": model, "serial": serial,
            "family": profile[0], "channels": profile[1], "simulated": False,
            "validation": "Hardware validation pending"}


def numbers(reply, count):
    try:
        result = [float(x) for x in reply.strip().split(",")]
    except ValueError as exc:
        raise DeviceError("The oscilloscope returned malformed numeric metadata.") from exc
    if len(result) != count or not all(math.isfinite(x) for x in result):
        raise DeviceError("The oscilloscope returned invalid waveform metadata.")
    return result


def waveform(times, volts):
    times, volts = np.asarray(times, dtype=float), np.asarray(volts, dtype=float)
    if (times.ndim != 1 or volts.shape != times.shape or not 2 <= len(times) <= MAX_POINTS
            or not np.isfinite(times).all() or not np.isfinite(volts).all()
            or not (np.diff(times) > 0).all()):
        raise DeviceError("Invalid waveform: expected matching, finite samples and increasing times.")
    return {"time_s": times.tolist(), "voltage_v": volts.tolist(),
            "points": len(times), "mean_v": float(np.mean(volts)),
            "rms_v": float(np.sqrt(np.mean(volts ** 2))),
            "peak_to_peak_v": float(np.ptp(volts))}


class Simulator:
    def __init__(self):
        self.info = {"vendor": "Simulator", "model": "Four-channel oscilloscope", "serial": "SIM-001",
                     "family": "sim", "channels": 4, "simulated": True,
                     "validation": "Synthetic data"}
        self.timebase = 0.001
        self.channels = [{"scale_v": 1.0, "coupling": "DC", "enabled": True} for _ in range(4)]
        self.state = "RUN"
        self.phase = 0.0

    def settings(self, channel):
        return {"channel": channel, "timebase_s": self.timebase,
                "acquisition_state": self.state, **self.channels[channel - 1]}

    def configure(self, req: Settings):
        if req.timebase_s is not None:
            self.timebase = req.timebase_s
        for key in ("scale_v", "coupling"):
            if getattr(req, key) is not None:
                self.channels[req.channel - 1][key] = getattr(req, key)

    def action(self, action):
        if action == "autoscale":
            self.timebase = 0.0002
            for channel in self.channels:
                channel.update(scale_v=0.5, coupling="DC")
        elif action == "single":
            self.phase += 0.1
            self.state = "STOP"
        else:
            self.state = action.upper()

    def capture(self, channel):
        if self.state == "RUN":
            self.phase += 0.05
        t = np.linspace(-6 * self.timebase, 6 * self.timebase, 1200, endpoint=False)
        y = (1.5 / channel) * np.sin(2 * np.pi * 1000 * t + self.phase + (channel - 1) * 0.6)
        if self.channels[channel - 1]["coupling"] == "GND":
            y *= 0
        return waveform(t, y)

    def close(self):
        pass


class VisaScope:
    def __init__(self, instrument, info):
        self.instrument, self.info = instrument, info

    @property
    def rigol(self):
        return self.info["family"] == "rigol"

    def number(self, command):
        return numbers(self.instrument.query(command), 1)[0]

    def settings(self, channel):
        p = f":CHAN{channel}"
        return {"channel": channel,
                "timebase_s": self.number(":TIM:MAIN:SCAL?" if self.rigol else ":TIM:SCAL?"),
                "scale_v": self.number(p + ":SCAL?"),
                "coupling": self.instrument.query(p + ":COUP?").strip(),
                "enabled": self.instrument.query(p + (":DISP?" if self.rigol else ":STAT?")).strip() in ("1", "ON"),
                "acquisition_state": self.instrument.query(":TRIG:STAT?" if self.rigol else ":ACQ:STAT?").strip()}

    def check_error(self):
        reply = self.instrument.query(":SYST:ERR?").strip()
        try:
            code = int(reply.split(",")[0])
        except ValueError as exc:
            raise DeviceError(f"Invalid instrument error response: {reply}") from exc
        if code:
            raise ScopeError(f"Instrument reported {reply}. Settings may have been partially applied; refresh them.")

    def configure(self, req: Settings):
        # Detect pre-existing errors before making changes; do not silently clear them.
        self.check_error()
        if req.timebase_s is not None:
            command = ":TIM:MAIN:SCAL" if self.rigol else ":TIM:SCAL"
            self.instrument.write(f"{command} {req.timebase_s:.12g}")
        if req.scale_v is not None:
            self.instrument.write(f":CHAN{req.channel}:SCAL {req.scale_v:.12g}")
        if req.coupling is not None:
            self.instrument.write(f":CHAN{req.channel}:COUP {req.coupling}")
        self.check_error()

    def action(self, action):
        commands = {"run": ":RUN", "stop": ":STOP", "single": ":SING", "autoscale": ":AUT"}
        self.check_error()
        self.instrument.write(commands[action])
        self.check_error()

    def block(self, command, expected_bytes):
        """Read a bounded IEEE definite-length block, including its LF/CRLF trailer.

        Disable VISA termination during binary reads: sample bytes may contain LF.
        A framing failure invalidates the session in the manager (no stale replies).
        """
        inst = self.instrument
        termination = inst.read_termination
        inst.read_termination = None
        try:
            inst.write(command)
            prefix = inst.read_bytes(2)
            if len(prefix) != 2 or prefix[0:1] != b"#" or prefix[1:2] not in b"123456789":
                raise DeviceError("Expected an IEEE definite-length waveform block.")
            digits = inst.read_bytes(int(prefix[1:2]))
            if not digits.isdigit() or int(digits) != expected_bytes or expected_bytes > MAX_POINTS * 4:
                raise DeviceError("Waveform block length does not match its metadata or exceeds the limit.")
            data = inst.read_bytes(expected_bytes)
            if len(data) != expected_bytes:
                raise DeviceError("Truncated waveform block.")
            end = inst.read_bytes(1)
            if end == b"\r":
                end = inst.read_bytes(1)
            if end != b"\n":
                raise DeviceError("Missing waveform block terminator.")
            return data
        finally:
            inst.read_termination = termination

    def capture(self, channel):
        i = self.instrument
        enabled = i.query(f":CHAN{channel}" + (":DISP?" if self.rigol else ":STAT?")).strip()
        if enabled not in ("1", "ON"):
            raise ScopeError(f"CH{channel} is disabled. Enable it on the oscilloscope front panel first.")
        self.check_error()
        if self.rigol:
            for cmd in (f":WAV:SOUR CHAN{channel}", ":WAV:MODE NORM", ":WAV:FORM BYTE", ":WAV:STAR 1", ":WAV:STOP 1200"):
                i.write(cmd)
            fmt, mode, n, count, dx, x0, xr, dy, y0, yr = numbers(i.query(":WAV:PRE?"), 10)
            if fmt != 0 or mode != 0 or n != int(n) or not 2 <= n <= 1200 or dx <= 0 or dy <= 0:
                raise DeviceError("Unsupported RIGOL screen waveform preamble.")
            raw = np.frombuffer(self.block(":WAV:DATA?", int(n)), dtype=np.uint8).astype(float)
            result = waveform((np.arange(int(n)) - xr) * dx + x0, (raw - y0 - yr) * dy)
        else:
            for cmd in (f":CHAN{channel}:DATA:POIN DEF", ":FORM REAL,32", ":FORM:BORD LSBF"):
                i.write(cmd)
            start, stop, n, values_per_sample = numbers(i.query(f":CHAN{channel}:DATA:HEAD?"), 4)
            if n != int(n) or not 2 <= n <= MAX_POINTS or stop <= start:
                raise DeviceError("Invalid HMO screen waveform header.")
            if values_per_sample != 1:
                raise ScopeError("Peak-detect/envelope data are not supported. Select a normal acquisition on the scope.")
            data = np.frombuffer(self.block(f":CHAN{channel}:DATA?", int(n) * 4), dtype="<f4")
            result = waveform(np.linspace(start, stop, int(n)), data)
        self.check_error()
        return result

    def close(self):
        self.instrument.close()


class VisaProvider:
    def __init__(self, library=None):
        self.library, self.rm = library, None

    def manager(self):
        if self.rm is None:
            try:
                import pyvisa
                self.rm = pyvisa.ResourceManager(self.library) if self.library else pyvisa.ResourceManager()
            except Exception as exc:
                raise DeviceError(f"Cannot load VISA: {exc}. Install the lab's VISA runtime or start with --visa-library @py.") from exc
        return self.rm

    def resources(self):
        # Enumeration only: never send commands to every COM port on a lab PC.
        return [r for r in self.manager().list_resources()
                if re.fullmatch(r"(?:USB[^\r\n]*|ASRL[^\r\n]*)::INSTR", r, re.I)]

    def connect(self, req: Connection):
        if not re.fullmatch(r"(?:USB[^\r\n]*|ASRL[^\r\n]*)::INSTR", req.resource, re.I):
            raise ScopeError("Choose a USB…::INSTR or ASRL…::INSTR VISA resource.")
        inst = self.manager().open_resource(req.resource)
        try:
            from pyvisa import constants
            inst.timeout = req.timeout_ms
            term = {"LF": "\n", "CRLF": "\r\n", "CR": "\r"}[req.termination]
            inst.write_termination = term
            inst.read_termination = term
            if req.resource.upper().startswith("ASRL"):
                inst.baud_rate = req.baud_rate
                inst.data_bits = 8
                inst.parity = constants.Parity.none
                inst.stop_bits = constants.StopBits.one
                inst.flow_control = {"none": constants.ControlFlow.none,
                                     "rts_cts": constants.ControlFlow.rts_cts,
                                     "xon_xoff": constants.ControlFlow.xon_xoff}[req.flow_control]
            info = identify(inst.query("*IDN?").strip())
            info["resource"] = req.resource
            return VisaScope(inst, info)
        except Exception:
            with suppress(Exception):
                inst.close()
            raise

    def close(self):
        if self.rm is not None:
            self.rm.close()
            self.rm = None
