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
        VisaScope(inst, identify("HAMEG,HMO3524,123,1")).capture(1)
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


HMO_REPLIES = {":TIM:SCAL?": "0.001", ":CHAN1:SCAL?": "0.5", ":CHAN1:COUP?": "DCL", ":CHAN1:STAT?": "1",
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
