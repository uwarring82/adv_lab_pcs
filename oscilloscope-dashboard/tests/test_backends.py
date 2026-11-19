import struct

import numpy as np
import pytest

from scope.backends import DeviceError, ScopeError, VisaProvider, VisaScope, identify, numbers
from scope.models import Connection, Settings


class Instrument:
    """A VISA peer with independent text replies and a binary byte stream."""
    def __init__(self, replies=None, payload=b""):
        self.replies = replies or {}
        self.payload = payload
        self.writes = []
        self.read_termination = "\n"
        self.closed = False

    def query(self, command):
        self.writes.append(command)
        if command == ":SYST:ERR?":
            return self.replies.get(command, '0,"No error"')
        return self.replies[command]

    def write(self, command):
        self.writes.append(command)

    def read_bytes(self, count):
        result, self.payload = self.payload[:count], self.payload[count:]
        return result

    def close(self):
        self.closed = True


def block(payload):
    length = str(len(payload)).encode()
    return b"#" + str(len(length)).encode() + length + payload + b"\n"


def rigol(inst):
    return VisaScope(inst, identify("RIGOL TECHNOLOGIES,DS1054Z,SERIAL,00.04"))


@pytest.mark.parametrize("model,channels", [("DS1054Z", 4), ("DS1074Z", 4), ("DS1104Z Plus", 4), ("DS1202Z-E", 2)])
def test_rigol_identification(model, channels):
    assert identify(f"RIGOL TECHNOLOGIES,{model},123,1")["channels"] == channels


@pytest.mark.parametrize("vendor,model", [("HAMEG", "HMO1022"), ("Rohde&Schwarz", "HMO3524")])
def test_hmo_identification(vendor, model):
    assert identify(f"{vendor},{model},123,1")["family"] == "hmo"


@pytest.mark.parametrize("identity", ["HAMEG,HM1508,123,1", "HAMEG,HM1022,123,1", "UNKNOWN,DS1054Z,123,1", "garbage"])
def test_unverified_devices_rejected(identity):
    with pytest.raises(ScopeError):
        identify(identity)


def test_rigol_waveform_uses_both_references_and_origins():
    inst = Instrument({":CHAN2:DISP?": "1", ":WAV:PRE?": "0,0,4,1,0.000002,-0.000010,2,0.02,3,128"},
                      block(bytes([121, 131, 141, 10])))
    data = rigol(inst).capture(2)
    np.testing.assert_allclose(data["time_s"], [-14e-6, -12e-6, -10e-6, -8e-6])
    np.testing.assert_allclose(data["voltage_v"], [-0.2, 0, 0.2, -2.42])
    assert ":WAV:MODE NORM" in inst.writes
    assert ":STOP" not in inst.writes
    assert not inst.payload
    assert inst.read_termination == "\n"


def test_hmo_little_endian_volts_and_time_header():
    payload = struct.pack("<4f", -1.5, 0, 0.5, 2)
    inst = Instrument({":CHAN1:STAT?": "1", ":CHAN1:DATA:HEAD?": "-0.003,0.003,4,1"}, block(payload))
    backend = VisaScope(inst, identify("HAMEG,HMO1022,123,1"))
    data = backend.capture(1)
    np.testing.assert_allclose(data["time_s"], [-0.003, -0.001, 0.001, 0.003])
    np.testing.assert_allclose(data["voltage_v"], [-1.5, 0, 0.5, 2])
    assert data["peak_to_peak_v"] == 3.5
    assert ":CHAN1:DATA:POIN DEF" in inst.writes
    assert ":FORM:BORD LSBF" in inst.writes


@pytest.mark.parametrize("payload", [b"#0abc\n", b"#9100000000", b"#14abc", b"#13abcX", b"#xjunk", b""])
def test_bad_block_is_rejected_without_large_read(payload):
    inst = Instrument(payload=payload)
    with pytest.raises(DeviceError):
        rigol(inst).block(":WAV:DATA?", 3)
    assert inst.read_termination == "\n"


def test_crlf_block():
    inst = Instrument(payload=b"#13abc\r\n")
    assert rigol(inst).block(":WAV:DATA?", 3) == b"abc"
    assert not inst.payload


def test_disabled_channel_not_silently_enabled():
    inst = Instrument({":CHAN1:DISP?": "0"})
    with pytest.raises(ScopeError, match="disabled"):
        rigol(inst).capture(1)
    assert inst.writes == [":CHAN1:DISP?"]


def test_hmo_peak_detect_rejected_before_data_transfer():
    inst = Instrument({":CHAN1:STAT?": "1", ":CHAN1:DATA:HEAD?": "0,1,1200,2"})
    with pytest.raises(ScopeError, match="Peak-detect"):
        VisaScope(inst, identify("HAMEG,HMO1022,123,1")).capture(1)
    assert ":CHAN1:DATA?" not in inst.writes


def test_scpi_errors_are_not_reported_as_success():
    inst = Instrument({":SYST:ERR?": '-222,"Data out of range"'})
    with pytest.raises(ScopeError, match="-222"):
        rigol(inst).configure(Settings(scale_v=2))
    assert inst.writes == [":SYST:ERR?"]


def test_hmo_and_rigol_timebase_commands():
    for family, expected in [("rigol", ":TIM:MAIN:SCAL 0.001"), ("hmo", ":TIM:SCAL 0.001")]:
        inst = Instrument()
        VisaScope(inst, {"family": family}).configure(Settings(timebase_s=0.001))
        assert expected in inst.writes


class ResourceManager:
    def __init__(self, inst):
        self.inst = inst
        self.opens = []

    def open_resource(self, name):
        self.opens.append(name)
        return self.inst

    def list_resources(self):
        return ("ASRL3::INSTR", "USB0::123::456::S::INSTR", "TCPIP0::192.0.2.1::INSTR")


def test_serial_settings_and_identity_before_commands():
    from pyvisa import constants
    inst = Instrument({"*IDN?": "HAMEG,HMO1022,123,1"})
    provider = VisaProvider()
    provider.rm = ResourceManager(inst)
    provider.connect(Connection(resource="ASRL3::INSTR", baud_rate=19200, flow_control="rts_cts", termination="CRLF"))
    assert inst.baud_rate == 19200
    assert inst.data_bits == 8
    assert inst.parity == constants.Parity.none
    assert inst.stop_bits == constants.StopBits.one
    assert inst.flow_control == constants.ControlFlow.rts_cts
    assert inst.write_termination == inst.read_termination == "\r\n"
    assert inst.writes == ["*IDN?"]


def test_unknown_device_closes_handle_without_control_commands():
    inst = Instrument({"*IDN?": "HAMEG,HM1508,123,1"})
    provider = VisaProvider()
    provider.rm = ResourceManager(inst)
    with pytest.raises(ScopeError):
        provider.connect(Connection(resource="ASRL3::INSTR"))
    assert inst.closed
    assert inst.writes == ["*IDN?"]


def test_discovery_does_not_probe_resources():
    provider = VisaProvider()
    provider.rm = ResourceManager(Instrument())
    assert len(provider.resources()) == 2
    assert provider.rm.opens == []


@pytest.mark.parametrize("resource", ["TCPIP0::192.0.2.1::INSTR", "ASRL3::INSTR\n*RST", "COM3"])
def test_invalid_resource_rejected_before_open(resource):
    provider = VisaProvider()
    provider.rm = ResourceManager(Instrument())
    with pytest.raises(ScopeError):
        provider.connect(Connection(resource=resource))
    assert provider.rm.opens == []


@pytest.mark.parametrize("value", ["NaN", "inf", "1,2", "not a number"])
def test_bad_numeric_metadata(value):
    with pytest.raises(DeviceError):
        numbers(value, 1)


class TimeoutInstrument(Instrument):
    """Raises a VISA-like timeout for chosen commands; records clear()."""
    def __init__(self, silent=(), **kw):
        super().__init__(**kw)
        self.silent, self.cleared = set(silent), False

    def query(self, command):
        if command in self.silent:
            self.writes.append(command)
            raise TimeoutError("VI_ERROR_TMO (-1073807339): Timeout expired before operation completed.")
        return super().query(command)

    def clear(self):
        self.cleared = True


HMO_REPLIES = {":TIM:SCAL?": "0.001", ":HOR:MAIN:SCAL?": "0.001",
               ":CHAN1:SCAL?": "0.5", ":CHAN1:COUP?": "DC", ":CHAN1:STAT?": "1",
               ":ACQ:STAT?": "RUN"}


def test_unanswered_status_query_reports_unknown_state_and_clears_input():
    inst = TimeoutInstrument(silent={":ACQ:STAT?"}, replies=HMO_REPLIES)
    settings = VisaScope(inst, identify("HAMEG,HMO3524,123,1")).settings(1)
    assert settings["acquisition_state"] == "UNKNOWN"
    assert settings["scale_v"] == 0.5 and inst.cleared


def test_unanswered_essential_query_names_the_command():
    inst = TimeoutInstrument(silent={":CHAN1:COUP?"}, replies=HMO_REPLIES)
    with pytest.raises(DeviceError, match=r":CHAN1:COUP\? .*HMO3524.*VI_ERROR_TMO"):
        VisaScope(inst, identify("HAMEG,HMO3524,123,1")).settings(1)


def test_block_timeout_names_the_command_and_restores_termination():
    class Slow(Instrument):
        def read_bytes(self, count):
            raise TimeoutError("VI_ERROR_TMO")
    inst = Slow()
    with pytest.raises(DeviceError, match=r":CHAN1:DATA\?"):
        VisaScope(inst, identify("HAMEG,HMO3524,123,1")).block(":CHAN1:DATA?", 4)
    assert inst.read_termination == "\n"


# --- rc5: serial log, diagnosis, serial hints -------------------------------------------------

class SerialPeer(Instrument):
    """Byte-level serial peer: answers chosen commands, stays silent for the others."""
    def __init__(self, answers, **kw):
        super().__init__(replies=dict(answers), **kw)
        self.answers, self.buffer, self.timeout = answers, b"", 5000
        self.write_termination = "\n"
        self.flushed = 0

    def write_raw(self, data):
        command = data.decode().strip()
        self.writes.append(command)
        if command in self.answers:
            self.buffer += (self.answers[command] + "\r\n").encode()

    def read_bytes(self, count):
        if not self.buffer:
            raise TimeoutError("VI_ERROR_TMO")
        result, self.buffer = self.buffer[:count], self.buffer[count:]
        return result

    def flush(self, mask):
        self.flushed += 1
        self.buffer = b""


def test_trace_log_records_every_exchange(tmp_path, monkeypatch):
    from scope import trace
    monkeypatch.setattr(trace, "log_dir", lambda: tmp_path)
    inst = Instrument({"*IDN?": "HAMEG,HMO3524,123,1"})
    provider = VisaProvider()
    provider.rm = ResourceManager(inst)
    scope = provider.connect(Connection(resource="ASRL3::INSTR", trace=True, settle_ms=0))
    text = open(scope.info["trace_file"], encoding="utf-8").read()
    assert "baud=115200" in text and "flow=none" in text
    assert "TX" in text and "*IDN?" in text and "RX" in text and "HMO3524" in text
    assert "hex=" in text


def test_trace_log_records_timeouts(tmp_path, monkeypatch):
    from scope import trace
    monkeypatch.setattr(trace, "log_dir", lambda: tmp_path)
    inst = TimeoutInstrument(silent={"*IDN?"})
    provider = VisaProvider()
    provider.rm = ResourceManager(inst)
    with pytest.raises(TimeoutError):
        provider.connect(Connection(resource="ASRL3::INSTR", trace=True))
    assert "ERR" in next(tmp_path.glob("*.txt")).read_text(encoding="utf-8")


def test_serial_timeout_error_names_link_and_next_steps():
    inst = TimeoutInstrument(silent={":HOR:MAIN:SCAL?"}, replies=HMO_REPLIES)
    scope = VisaScope(inst, identify("HAMEG,HMO3524,123,1"), "115200 baud 8N1, flow none, line end LF")
    with pytest.raises(DeviceError, match=r"115200 baud.*flow none.*Diagnose serial link"):
        scope.settings(1)


def test_usb_timeout_error_has_no_serial_hint():
    inst = TimeoutInstrument(silent={":HOR:MAIN:SCAL?"}, replies=HMO_REPLIES)
    with pytest.raises(DeviceError) as err:
        VisaScope(inst, identify("HAMEG,HMO3524,123,1")).settings(1)
    assert "Serial link" not in str(err.value)


# HMO3524 uses the legacy horizontal/trace dialect, not HMO Compact's timebase/data API.
def legacy_hmo(inst):
    return VisaScope(inst, identify("HAMEG,HMO3524,TEST,SW02.030"))


def test_hmo3524_settings_and_writes_use_legacy_timebase():
    inst = Instrument({key: value for key, value in HMO_REPLIES.items() if key != ":TIM:SCAL?"})
    backend = legacy_hmo(inst)
    settings = backend.settings(1)
    assert settings["timebase_s"] == 0.001
    assert settings["coupling"] == "DC" and settings["enabled"] is True
    backend.configure(Settings(timebase_s=0.00001, scale_v=5, coupling="AC"))
    assert ":HOR:MAIN:SCAL 1e-05" in inst.writes
    assert ":CHAN1:SCAL 5" in inst.writes and ":CHAN1:COUP AC" in inst.writes
    assert not any(command.startswith(":TIM") for command in inst.writes)
    assert backend.info["protocol"] == "hmo3524_legacy"
    assert backend.info["unsupported_actions"] == ["autoscale"]


@pytest.mark.parametrize("action,commands", [
    ("run", [":ACQ:STAT RUN"]), ("stop", [":ACQ:STAT STOP"]),
    ("single", [":TRIG:A:MODE SING", ":ACQ:STAT RUN"]),
])
def test_hmo3524_actions_use_documented_commands(action, commands):
    inst = Instrument()
    legacy_hmo(inst).action(action)
    assert inst.writes == [":SYST:ERR?", *commands, ":SYST:ERR?"]


def test_hmo3524_auto_setup_rejected_before_instrument_contact():
    inst = Instrument()
    with pytest.raises(ScopeError, match="front panel"):
        legacy_hmo(inst).action("autoscale")
    assert inst.writes == []


LEGACY_TRACE_REPLIES = {":CHAN2:STAT?": "ON", ":TRAC:TYPE?": "NORM", ":TRAC:POIN?": "4",
                       ":TRAC:XINC?": "0.000001", ":TRAC:XOR?": "-0.003", ":TRAC:XREF?": "1",
                       ":TRAC:YINC?": "0.02", ":TRAC:YOR?": "-1.5", ":TRAC:YREF?": "128"}


def test_hmo3524_byte_capture_preserves_both_origins_references_and_unsigned_values():
    inst = Instrument(LEGACY_TRACE_REPLIES, block(bytes([10, 128, 190, 255])))
    data = legacy_hmo(inst).capture(2)
    np.testing.assert_allclose(data["time_s"], [-0.003001, -0.003, -0.002999, -0.002998])
    np.testing.assert_allclose(data["voltage_v"], [-3.86, -1.5, -0.26, 1.04])
    assert ":TRAC:SOUR CH2" in inst.writes and ":TRAC:FORM BYTE" in inst.writes
    assert ":TRAC:POIN DEF" in inst.writes and ":TRAC:DATA?" in inst.writes
    assert not any(command.startswith((":TIM", ":FORM", ":CHAN2:DATA")) for command in inst.writes)
    assert not inst.payload and inst.read_termination == "\n"


@pytest.mark.parametrize("count", ["0", "1", "20001", "4.5", "9.91e37", "NaN"])
def test_hmo3524_invalid_count_prevents_binary_read(count):
    inst = Instrument(LEGACY_TRACE_REPLIES | {":TRAC:POIN?": count})
    with pytest.raises(DeviceError):
        legacy_hmo(inst).capture(2)
    assert ":TRAC:DATA?" not in inst.writes


@pytest.mark.parametrize("field,value", [("XINC", "0"), ("XINC", "-1"), ("YINC", "0"),
                                        ("XOR", "9.91e37"), ("YREF", "NaN")])
def test_hmo3524_invalid_scaling_prevents_binary_read(field, value):
    inst = Instrument(LEGACY_TRACE_REPLIES | {f":TRAC:{field}?": value})
    with pytest.raises(DeviceError):
        legacy_hmo(inst).capture(2)
    assert ":TRAC:DATA?" not in inst.writes


def test_hmo3524_minmax_trace_is_rejected_without_changing_acquisition():
    inst = Instrument(LEGACY_TRACE_REPLIES | {":TRAC:TYPE?": "MINMAX"})
    with pytest.raises(ScopeError, match="Peak-detect"):
        legacy_hmo(inst).capture(2)
    assert ":TRAC:DATA?" not in inst.writes
    assert not any(command.startswith(":ACQ") for command in inst.writes)


def test_diagnosis_logs_bytes_and_finds_the_silent_command(tmp_path, monkeypatch):
    from scope import trace
    monkeypatch.setattr(trace, "log_dir", lambda: tmp_path)
    monkeypatch.setattr(trace.time, "sleep", lambda s: None)
    peer = SerialPeer({"*IDN?": "HAMEG,HMO3524,123,1", ":SYST:ERR?": '0,"No error"', "*OPC?": "1"})
    provider = VisaProvider()
    provider.rm = ResourceManager(peer)
    result = provider.diagnose(Connection(resource="ASRL3::INSTR"))
    failed = [s["command"] for s in result["steps"] if not s["ok"]]
    assert ":TIM:SCAL?" in failed and ":TIMebase:SCALe?" in failed and "*IDN?" not in failed
    text = open(result["log_file"], encoding="utf-8").read()
    assert "RXB" in text and "hex=" in text and "no reply" in text
    assert peer.closed and peer.flushed > 0
    assert peer.baud_rate == 115200


def test_diagnosis_stops_when_identification_is_silent(tmp_path, monkeypatch):
    from scope import trace
    monkeypatch.setattr(trace, "log_dir", lambda: tmp_path)
    monkeypatch.setattr(trace.time, "sleep", lambda s: None)
    peer = SerialPeer({})
    provider = VisaProvider()
    provider.rm = ResourceManager(peer)
    result = provider.diagnose(Connection(resource="ASRL3::INSTR"))
    assert peer.writes == ["*IDN?"] and len(result["steps"]) == 1


def test_diagnosis_refuses_usb_resource():
    provider = VisaProvider()
    provider.rm = ResourceManager(Instrument())
    with pytest.raises(ScopeError):
        provider.diagnose(Connection(resource="USB0::1::2::S::INSTR"))
    assert provider.rm.opens == []


def test_timeout_log_line_reports_waiting_bytes(tmp_path, monkeypatch):
    from scope import trace
    monkeypatch.setattr(trace, "log_dir", lambda: tmp_path)
    inst = TimeoutInstrument(silent={":TIM:SCAL?"})
    inst.bytes_in_buffer, inst.write_termination = 7, "\n"
    traced = trace.TracedInstrument(inst, trace.TraceLog())
    with pytest.raises(TimeoutError):
        traced.query(":TIM:SCAL?")
    assert "bytes waiting in receive buffer: 7" in next(tmp_path.glob("*.txt")).read_text(encoding="utf-8")


@pytest.mark.parametrize('next_step_firmware', [False, True])
@pytest.mark.parametrize('requested,previous', [(1e-5,5e-6),(2e-5,1e-5),(5e-5,2e-5)])
def test_legacy_timebase_corrects_only_observed_next_step(next_step_firmware, requested, previous):
    class Timebase(Instrument):
        value = .001
        def write(self, command):
            super().write(command)
            if command.startswith(':HOR:MAIN:SCAL '):
                value = float(command.split()[1])
                self.value = {5e-6:1e-5,1e-5:2e-5,2e-5:5e-5,5e-5:1e-4}[value] if next_step_firmware else value
        def query(self, command):
            if command == ':HOR:MAIN:SCAL?':
                self.writes.append(command)
                return str(self.value)
            return super().query(command)
    inst = Timebase()
    legacy_hmo(inst).configure(Settings(timebase_s=requested))
    assert inst.value == pytest.approx(requested)
    setters = [s for s in inst.writes if s.startswith(':HOR:MAIN:SCAL ')]
    expected = [f':HOR:MAIN:SCAL {requested:.12g}']
    if next_step_firmware: expected.append(f':HOR:MAIN:SCAL {previous:.12g}')
    assert setters == expected


def test_legacy_timebase_correction_is_bounded_and_reports_failed_readback():
    inst = Instrument({':HOR:MAIN:SCAL?': '2e-5'})
    with pytest.raises(ScopeError, match='Timebase correction did not reach'):
        legacy_hmo(inst).configure(Settings(timebase_s=1e-5))
    assert [s for s in inst.writes if s.startswith(':HOR:MAIN:SCAL ')] == [
        ':HOR:MAIN:SCAL 1e-05', ':HOR:MAIN:SCAL 5e-06']


def test_legacy_timebase_read_failure_never_resends_setter():
    class FailedRead(Instrument):
        def query(self, command):
            if command == ':HOR:MAIN:SCAL?':
                raise TimeoutError('read failed')
            return super().query(command)
    inst = FailedRead()
    with pytest.raises(DeviceError, match='read failed'):
        legacy_hmo(inst).configure(Settings(timebase_s=1e-5))
    assert [s for s in inst.writes if s.startswith(':HOR:MAIN:SCAL ')] == [':HOR:MAIN:SCAL 1e-05']
