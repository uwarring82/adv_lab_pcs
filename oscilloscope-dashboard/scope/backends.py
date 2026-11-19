"""Model-specific SCPI drivers. Protocol references and limits are in README.md."""
from __future__ import annotations

import math
import re
import time
from contextlib import suppress

import numpy as np

from . import trace
from .models import Connection, Settings

MAX_POINTS = 20000
SETTLE_S = 0.1  # after *IDN? on a serial line
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
            "protocol": "hmo3524_legacy" if key == "HMO3524" else profile[0],
            "unsupported_actions": ["autoscale"] if key == "HMO3524" else [],
            "validation": ("Mac USB capture, controls and CSV scaling checked; Windows RS-232 pending"
                           if key == "HMO3524" else "Hardware validation pending")}


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


def legacy_timebase_neighbors(value):
    """Previous/next standard 1-2-5 setting, or None for a nonstandard request."""
    decade = 10 ** math.floor(math.log10(value))
    for nominal, previous, following in ((1, .5, 2), (2, 1, 5), (5, 2, 10)):
        if math.isclose(value, nominal * decade, rel_tol=1e-6):
            return previous * decade, following * decade
    return None


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
    def __init__(self, instrument, info, link=""):
        self.instrument, self.info, self.link = instrument, info, link
        self.serial = bool(link)

    @property
    def rigol(self):
        return self.info["family"] == "rigol"

    @property
    def legacy_hmo(self):
        return self.info.get("protocol") == "hmo3524_legacy"

    @property
    def timebase_command(self):
        if self.rigol:
            return ":TIM:MAIN:SCAL"
        return ":HOR:MAIN:SCAL" if self.legacy_hmo else ":TIM:SCAL"

    def ask(self, command):
        """Query with the failing command named in the error (a bare VISA timeout does not say which)."""
        if self.serial:
            trace.discard_input(self.instrument)  # no stale or late bytes from an earlier exchange
        try:
            return self.instrument.query(command)
        except (ScopeError, KeyboardInterrupt):
            raise
        except Exception as exc:
            if self.link.startswith("HO720 USB"):
                hint = (" HO720 USB: check that USB is active, close other control programs, "
                        "then run 'Diagnose serial link / HO720 USB' and send the log file.")
            else:
                hint = (f" Serial link: {self.link}. The instrument answered *IDN? but not this command: try "
                        "another baud rate (9600 or 19200), another flow control or line ending, or run "
                        "'Diagnose serial link' and send the log file." if self.serial else "")
            raise DeviceError(f"No usable reply to {command} from {self.info.get('model', 'instrument')} ({exc}). "
                              f"Report this command; check the serial settings and the instrument's remote setting.{hint}") from exc

    def ask_optional(self, command, default="UNKNOWN"):
        """Status-only query: if the model does not answer it, report UNKNOWN instead of failing the connection."""
        try:
            return self.instrument.query(command).strip() or default
        except (ScopeError, KeyboardInterrupt):
            raise
        except Exception:
            with suppress(Exception):
                self.instrument.clear()  # drop a late or partial reply before the next command
            return default

    def number(self, command):
        return numbers(self.ask(command), 1)[0]

    def settings(self, channel):
        p = f":CHAN{channel}"
        return {"channel": channel,
                "timebase_s": self.number(self.timebase_command + "?"),
                "scale_v": self.number(p + ":SCAL?"),
                "coupling": self.ask(p + ":COUP?").strip(),
                "enabled": self.ask(p + (":DISP?" if self.rigol else ":STAT?")).strip() in ("1", "ON"),
                "acquisition_state": self.ask_optional(":TRIG:STAT?" if self.rigol else ":ACQ:STAT?")}

    def instrument_error(self):
        reply = self.ask(":SYST:ERR?").strip()
        try:
            code = int(reply.split(",")[0])
        except ValueError as exc:
            raise DeviceError(f"Invalid instrument error response: {reply}") from exc
        return code, reply

    def check_error(self, operation="settings", before=False):
        code, reply = self.instrument_error()
        if code:
            detail = (f"This error was pending before {operation}; no {operation} command was sent. "
                      "Inspect the instrument error queue before retrying." if before else
                      f"The error was reported after {operation}; check the instrument readback.")
            raise ScopeError(f"Instrument reported {reply}. {detail}")

    def configure(self, req: Settings):
        # Detect pre-existing errors before making changes; do not silently clear them.
        self.check_error(before=True)
        if req.timebase_s is not None:
            self.instrument.write(f"{self.timebase_command} {req.timebase_s:.12g}")
        if req.scale_v is not None:
            self.instrument.write(f":CHAN{req.channel}:SCAL {req.scale_v:.12g}")
        if req.coupling is not None:
            self.instrument.write(f":CHAN{req.channel}:COUP {req.coupling}")
        self.check_error()
        if self.legacy_hmo and req.timebase_s is not None:
            actual = self.number(self.timebase_command + "?")
            # The tested legacy firmware selects the next standard 1-2-5 step.
            # Adapt only to that observed readback; other firmware keeps the
            # normal setter. This is not a retry after a communication failure.
            neighbors = legacy_timebase_neighbors(req.timebase_s)
            if neighbors and math.isclose(actual, neighbors[1], rel_tol=1e-6):
                self.instrument.write(f"{self.timebase_command} {neighbors[0]:.12g}")
                self.check_error("timebase correction")
                corrected = self.number(self.timebase_command + "?")
                if not math.isclose(corrected, req.timebase_s, rel_tol=1e-6):
                    raise ScopeError(f"Timebase correction did not reach {req.timebase_s:g} s/div; "
                                     f"instrument reports {corrected:g} s/div. Read settings before retrying.")

    def action(self, action):
        if self.legacy_hmo:
            if action == "autoscale":
                raise ScopeError("Auto setup is not supported by the HMO3524 driver. Use the oscilloscope front panel.")
            commands = {"run": (":ACQ:STAT RUN",), "stop": (":ACQ:STAT STOP",),
                        "single": (":TRIG:A:MODE SING", ":ACQ:STAT RUN")}
        else:
            commands = {"run": (":RUN",), "stop": (":STOP",), "single": (":SING",), "autoscale": (":AUT",)}
        self.check_error(action, before=True)
        for command in commands[action]:
            self.instrument.write(command)
        self.check_error(action)

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
        except ScopeError:
            raise
        except Exception as exc:
            raise DeviceError(f"No usable data block in reply to {command} from {self.info.get('model', 'instrument')} ({exc}). "
                              "Report this command; check the serial settings and the instrument's remote setting.") from exc
        finally:
            inst.read_termination = termination

    def capture(self, channel):
        i = self.instrument
        enabled = self.ask(f":CHAN{channel}" + (":DISP?" if self.rigol else ":STAT?")).strip()
        if enabled not in ("1", "ON"):
            raise ScopeError(f"CH{channel} is disabled. Enable it on the oscilloscope front panel first.")
        self.check_error("capture", before=True)
        if self.rigol:
            for cmd in (f":WAV:SOUR CHAN{channel}", ":WAV:MODE NORM", ":WAV:FORM BYTE", ":WAV:STAR 1", ":WAV:STOP 1200"):
                i.write(cmd)
            fmt, mode, n, count, dx, x0, xr, dy, y0, yr = numbers(self.ask(":WAV:PRE?"), 10)
            if fmt != 0 or mode != 0 or n != int(n) or not 2 <= n <= 1200 or dx <= 0 or dy <= 0:
                raise DeviceError("Unsupported RIGOL screen waveform preamble.")
            raw = np.frombuffer(self.block(":WAV:DATA?", int(n)), dtype=np.uint8).astype(float)
            result = waveform((np.arange(int(n)) - xr) * dx + x0, (raw - y0 - yr) * dy)
        elif self.legacy_hmo:
            # HMO3522/3524 manual, trace commands (pp. 28-31): unsigned byte codes,
            # separate X/Y references and origins. HMO Compact's REAL32 API differs.
            for cmd in (f":TRAC:SOUR CH{channel}", ":TRAC:FORM BYTE", ":TRAC:POIN DEF"):
                i.write(cmd)
            if self.ask(":TRAC:TYPE?").strip().upper() not in ("NORM", "NORMAL"):
                raise ScopeError("Peak-detect/envelope data are not supported. Select a normal trace on the scope.")
            n = self.number(":TRAC:POIN?")
            if n != int(n) or not 2 <= n <= MAX_POINTS:
                raise DeviceError("Invalid HMO3524 screen waveform point count.")
            dx, x0, xr, dy, y0, yr = [self.number(":TRAC:" + key + "?")
                                     for key in ("XINC", "XOR", "XREF", "YINC", "YOR", "YREF")]
            if dx <= 0 or dy <= 0 or any(abs(v) >= 9e37 for v in (dx, x0, xr, dy, y0, yr)):
                raise DeviceError("Invalid HMO3524 screen waveform scaling.")
            self.check_error("waveform transfer setup")
            raw = np.frombuffer(self.block(":TRAC:DATA?", int(n)), dtype=np.uint8).astype(float)
            result = waveform((np.arange(int(n)) - xr) * dx + x0, (raw - yr) * dy + y0)
        else:
            for cmd in (f":CHAN{channel}:DATA:POIN DEF", ":FORM REAL,32", ":FORM:BORD LSBF"):
                i.write(cmd)
            start, stop, n, values_per_sample = numbers(self.ask(f":CHAN{channel}:DATA:HEAD?"), 4)
            if n != int(n) or not 2 <= n <= MAX_POINTS or stop <= start:
                raise DeviceError("Invalid HMO screen waveform header.")
            if values_per_sample != 1:
                raise ScopeError("Peak-detect/envelope data are not supported. Select a normal acquisition on the scope.")
            data = np.frombuffer(self.block(f":CHAN{channel}:DATA?", int(n) * 4), dtype="<f4")
            result = waveform(np.linspace(start, stop, int(n)), data)
        self.check_error("waveform transfer")
        return result

    def close(self):
        self.instrument.close()


class VisaProvider:
    def __init__(self, library=None):
        self.library, self.rm = library, None
        self.last_diagnostics = None

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
        from . import ftdi
        found, errors = [], []
        try:
            found.extend(r for r in self.manager().list_resources()
                         if re.fullmatch(r"(?:USB[^\r\n]*|ASRL[^\r\n]*)::INSTR", r, re.I))
        except Exception as exc:
            errors.append(str(exc))
        try:
            found.extend(ftdi.resources())
        except DeviceError as exc:
            errors.append(str(exc))
        if not found and len(errors) == 2:
            raise DeviceError("Resource discovery failed. " + " ".join(errors))
        return found

    def _open(self, req: Connection):
        """Open the resource and apply the serial and termination settings; no command is sent."""
        if req.resource.lower().startswith("ftdi:"):
            from .ftdi import FtdiInstrument
            return FtdiInstrument(req)
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
        except Exception:
            with suppress(Exception):
                inst.close()
            raise
        return inst

    def _trace(self, inst, req: Connection, prefix="serial-log"):
        log = trace.TraceLog(prefix=prefix)
        backend = "PyFtdi HO720 USB (no VISA)" if req.resource.lower().startswith("ftdi:") else self._visa_info()
        trace.header(log, req.resource, req, backend)
        return log, trace.TracedInstrument(inst, log)

    def _visa_info(self):
        try:
            import pyvisa
            return f"pyvisa {pyvisa.__version__}, {self.manager().visalib}"
        except Exception as exc:
            return f"VISA library unknown ({exc})"

    def connect(self, req: Connection):
        self.last_diagnostics = None
        inst = self._open(req)
        log = None
        try:
            if req.trace:
                log, inst = self._trace(inst, req)
            direct_usb = req.resource.lower().startswith("ftdi:")
            for attempt in range(2 if direct_usb else 1):
                try:
                    info = identify(inst.query("*IDN?").strip())
                    break
                except TimeoutError:
                    if attempt == 1 or not direct_usb:
                        raise
                    if log:
                        log.note("HO720 identity timed out; settle and retry *IDN? once")
                    time.sleep(0.5)
                    trace.discard_input(inst, log)
            if req.resource.upper().startswith("ASRL") or direct_usb:
                # A serial reply may still be arriving (trailing CR/LF); drop it before the next query.
                time.sleep(max(SETTLE_S, req.settle_ms / 1000))
                trace.discard_input(inst, log)
            info["resource"] = req.resource
            if log:
                info["trace_file"] = str(log.path)
            link = (f"{'HO720 USB, ' if direct_usb else ''}{req.baud_rate} baud 8N1, "
                    f"flow {req.flow_control}, line end {req.termination}"
                    if req.resource.upper().startswith("ASRL") or direct_usb else "")
            backend = VisaScope(inst, info, link)
            if req.clear_status:
                inst.write("*CLS")
                info["status_cleared"] = True
            return backend
        except Exception as exc:
            if log:
                log.line("ERR", f"connect failed: {exc}")
            with suppress(Exception):
                inst.close()
            self.last_diagnostics = getattr(inst, "diagnostics", None)
            raise

    def diagnose(self, req: Connection):
        """Read-only query sequence with a byte-level log; closes the port again afterwards."""
        if not (re.fullmatch(r"ASRL[^\r\n]*::INSTR", req.resource, re.I)
                or req.resource.lower().startswith("ftdi:")):
            raise ScopeError("Diagnosis needs an ASRL…::INSTR (COM port) or HO720 USB resource.")
        inst = self._open(req)
        try:
            log, _ = self._trace(inst, req, prefix="diagnose")
            results = trace.diagnose(inst, log)  # raw resource: the byte reader logs itself
            return {"log_file": str(log.path), "steps": results}
        finally:
            with suppress(Exception):
                inst.close()

    def close(self):
        if self.rm is not None:
            self.rm.close()
            self.rm = None
