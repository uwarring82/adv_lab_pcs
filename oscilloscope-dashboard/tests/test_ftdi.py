"""Real PyFtdi/pyserial wrapper, with USB I/O replaced; never claim a real device."""
from copy import deepcopy
from types import SimpleNamespace

from fastapi.testclient import TestClient
import numpy as np
import pytest
from pyftdi.ftdi import Ftdi, FtdiError
from pyftdi.serialext import protocol_ftdi
from pyftdi.usbtools import UsbTools
from usb.core import USBError, USBTimeoutError

from scope import backends, ftdi, trace
from scope.app import create_app
from scope.backends import DeviceError, ScopeError, VisaProvider
from scope.manager import Manager
from scope.models import Connection


class Clock:
    value = 0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class UsbPeer:
    def __init__(self, clock):
        self.clock, self.pending, self.commands = clock, bytearray(), []
        self.closed, self.silent_idn, self.idn_attempts = False, 0, 0
        self.bad_block, self.short_write, self.bad_config = False, False, False
        self.timeouts = (5000, 5000)
        self.configurations = 0
        self.purges = 0
        self.reads = 0
        self.answers = {'*IDN?': 'HAMEG,HMO3524,TEST,SW02.030', '*OPC?': '1', ':HOR:MAIN:SCAL?': '1e-5',
                        ':CHAN1:SCAL?': '5', ':CHAN1:COUP?': 'DC', ':CHAN1:STAT?': 'ON',
                        ':ACQ:STAT?': 'COMP', ':SYST:ERR?': '0,"No error"',
                        ':TRAC:TYPE?': 'NORMAL', ':TRAC:POIN?': '4',
                        ':TRAC:XINC?': '1e-6', ':TRAC:XOR?': '-1e-6', ':TRAC:XREF?': '0',
                        ':TRAC:YINC?': '.02', ':TRAC:YOR?': '-1.5', ':TRAC:YREF?': '128'}

    def set_baudrate(self, baud, exact):
        self.configurations += 1
        self.baud = baud
        return baud

    def set_line_property(self, *args):
        self.line = args

    def set_flowctrl(self, flow):
        if self.bad_config:
            raise ValueError('bad configuration')
        self.flow = flow

    def set_dynamic_latency(self, *args):
        pass

    def purge_rx_buffer(self):
        self.purges += 1
        self.pending.clear()

    def read_data(self, count):
        self.reads += 1
        self.clock.sleep(.001)
        raw = bytes(self.pending[:count])
        del self.pending[:count]
        return raw

    def write_data(self, raw):
        command = raw.decode().strip()
        self.commands.append(command)
        if self.short_write:
            return len(raw) - 1
        if command == '*IDN?':
            self.idn_attempts += 1
            if self.idn_attempts <= self.silent_idn:
                return len(raw)
        if command == ':TRAC:DATA?':
            self.pending.extend((b'#15' if self.bad_block else b'#14') + bytes([10, 128, 190, 255]) + b'\n')
        elif command in self.answers:
            self.pending.extend((self.answers[command] + '\n').encode())
        return len(raw)

    def close(self):
        self.closed = True


@pytest.fixture
def usb(monkeypatch):
    clock, opened, peers = Clock(), [], []
    monkeypatch.setattr(ftdi, 'time', clock)
    monkeypatch.setattr(backends, 'time', clock)
    monkeypatch.setattr(protocol_ftdi, 'now', clock.monotonic)
    monkeypatch.setattr(protocol_ftdi, 'sleep', clock.sleep)
    monkeypatch.setattr(Ftdi, 'PRODUCT_IDS', deepcopy(Ftdi.PRODUCT_IDS))

    def create(url):
        opened.append(url)
        peer = peers.pop(0) if peers else UsbPeer(clock)
        return peer

    monkeypatch.setattr(Ftdi, 'create_from_url', create)
    monkeypatch.setattr(Ftdi, 'list_devices', lambda url: [])
    return SimpleNamespace(clock=clock, opened=opened, peers=peers)


def test_discovery_is_specific_and_does_not_send_commands(usb, monkeypatch):
    device = SimpleNamespace(vid=ftdi.VID, pid=ftdi.PID, bus=1, address=2)
    other = SimpleNamespace(vid=ftdi.VID, pid=0x6001, bus=1, address=3)
    seen = []
    monkeypatch.setattr(Ftdi, 'list_devices', lambda url: seen.append(url) or [(device, 1), (other, 1)])
    assert ftdi.resources() == ['ftdi://0x0403:0xed72:0x1:0x2/1']
    assert seen == [ftdi.URL] and usb.opened == []
    ftdi.resources()  # custom registration is idempotent
    assert list(Ftdi.PRODUCT_IDS[ftdi.VID].values()).count(ftdi.PID) == 1


def test_usb_discovery_works_without_visa(usb, monkeypatch):
    descriptor = SimpleNamespace(vid=ftdi.VID, pid=ftdi.PID, bus=None, address=None)
    monkeypatch.setattr(Ftdi, 'list_devices', lambda url: [(descriptor, 1)])
    provider = VisaProvider()
    def no_visa():
        raise DeviceError('VISA absent')
    monkeypatch.setattr(provider, 'manager', no_visa)
    assert provider.resources() == [ftdi.URL]
    assert usb.opened == []


def test_visa_discovery_survives_unavailable_usb_backend(monkeypatch):
    def unavailable():
        raise DeviceError('USB unavailable')
    monkeypatch.setattr(ftdi, '_driver', unavailable)
    provider = VisaProvider()
    provider.rm = SimpleNamespace(list_resources=lambda: ['ASRL3::INSTR'])
    assert provider.resources() == ['ASRL3::INSTR']


@pytest.mark.parametrize('resource', [
    'ftdi://0x0403:0x6001/1', 'ftdi://0x0403:0xed72/2', 'ftdi://0x0403:0xed72/?',
    'ftdi://0x0403:0xed72/1\n*RST', 'ftdi://0x0403:0xed72:unknown/1',
])
def test_non_ho720_or_invalid_url_rejected_before_open(usb, resource):
    with pytest.raises(ScopeError):
        VisaProvider().connect(Connection(resource=resource))
    assert usb.opened == []


def test_xon_xoff_rejected_before_open(usb):
    with pytest.raises(ScopeError, match='XON/XOFF'):
        VisaProvider().connect(Connection(resource=ftdi.URL, flow_control='xon_xoff'))
    assert usb.opened == []


def test_connect_capture_trace_and_disconnect_through_api_without_visa(usb, monkeypatch, tmp_path):
    provider = VisaProvider()
    monkeypatch.setattr(provider, 'manager', lambda: pytest.fail('FTDI connection must not load VISA'))
    monkeypatch.setattr(trace, 'log_dir', lambda: tmp_path)
    peer = UsbPeer(usb.clock)
    usb.peers.append(peer)
    with TestClient(create_app(manager=Manager(provider=provider))) as client:
        response = client.post('/api/connect', json={'resource': ftdi.URL, 'trace': True, 'timeout_ms': 500})
        assert response.status_code == 200
        assert peer.commands == ['*IDN?']
        assert usb.clock.value >= .5 and peer.line == (8, 1, 'N') and peer.flow == ''
        settings = client.get('/api/settings').json()
        assert settings['timebase_s'] == 1e-5 and settings['scale_v'] == 5
        result = client.post('/api/capture', json={'channel': 1})
        assert result.status_code == 200
        data = result.json()
        np.testing.assert_allclose(data['voltage_v'], [-3.86, -1.5, -.26, 1.04])
        assert data['points'] == 4
        assert peer.configurations == 1  # consuming reply bytes must not reconfigure the UART
        assert peer.purges == 0  # use quiet reads, not hardware resets between SCPI commands
        commands = list(peer.commands)
        reads = peer.reads
        diagnostics = client.get('/api/diagnostics').json()
        assert diagnostics['details']['last_command'] == ':SYST:ERR?'
        assert peer.commands == commands and peer.reads == reads  # cached, never new I/O
        assert 'TEST' not in str(diagnostics)  # identity replies are redacted from the cache
        assert client.get(f'/api/capture/{data["id"]}/csv').status_code == 200
        log = next(tmp_path.glob('*.txt')).read_text()
        assert 'PyFtdi HO720 USB (no VISA)' in log and ':TRAC:DATA?' in log
        assert client.post('/api/action', json={'action': 'autoscale'}).status_code == 422
        assert client.get('/api/status').json()['connected'] is True
        client.post('/api/disconnect', json={})
        assert peer.closed
        replacement = UsbPeer(usb.clock)
        usb.peers.append(replacement)
        assert client.post('/api/connect', json={'resource': ftdi.URL}).status_code == 200
        assert len(usb.opened) == 2 and replacement.commands == ['*IDN?']
        assert client.get(f'/api/capture/{data["id"]}/csv').status_code == 409
    assert replacement.closed


def test_only_identity_is_retried_and_failure_closes_port(usb):
    peer = UsbPeer(usb.clock)
    peer.silent_idn = 2
    usb.peers.append(peer)
    with pytest.raises(TimeoutError):
        VisaProvider().connect(Connection(resource=ftdi.URL, timeout_ms=100))
    assert peer.commands == ['*IDN?', '*IDN?'] and peer.closed


def test_silent_first_identity_can_recover(usb):
    peer = UsbPeer(usb.clock)
    peer.silent_idn = 1
    usb.peers.append(peer)
    backend = VisaProvider().connect(Connection(resource=ftdi.URL, timeout_ms=100))
    assert backend.info['model'] == 'HMO3524' and peer.commands == ['*IDN?', '*IDN?']
    backend.close()


def test_unknown_model_closes_port_before_control_commands(usb):
    peer = UsbPeer(usb.clock)
    peer.answers['*IDN?'] = 'HAMEG,UNSUPPORTED,TEST'
    usb.peers.append(peer)
    with pytest.raises(ScopeError):
        VisaProvider().connect(Connection(resource=ftdi.URL, clear_status=True))
    assert peer.commands == ['*IDN?'] and peer.closed


def test_failed_configuration_releases_claimed_device(usb):
    peer = UsbPeer(usb.clock)
    peer.bad_config = True
    usb.peers.append(peer)
    with pytest.raises(DeviceError, match='bad configuration'):
        ftdi.FtdiInstrument(Connection(resource=ftdi.URL))
    assert peer.closed and peer.commands == []


def test_bad_waveform_invalidates_api_connection(usb):
    peer = UsbPeer(usb.clock)
    peer.bad_block = True
    usb.peers.append(peer)
    with TestClient(create_app(manager=Manager(provider=VisaProvider()))) as client:
        assert client.post('/api/connect', json={'resource': ftdi.URL}).status_code == 200
        assert client.post('/api/capture', json={'channel': 1}).status_code == 503
        assert peer.closed and not client.get('/api/status').json()['connected']
        commands, reads = list(peer.commands), peer.reads
        diagnostics = client.get('/api/diagnostics').json()
        assert diagnostics['details']['last_command'] == ':TRAC:DATA?'
        assert diagnostics['details']['events'][-1]['phase'] == 'CLOSE'
        assert peer.commands == commands and peer.reads == reads


def test_failed_connection_preserves_write_failure_even_without_file_logging(usb):
    peer = UsbPeer(usb.clock)
    peer.short_write = True
    usb.peers.append(peer)
    with TestClient(create_app(manager=Manager(provider=VisaProvider()))) as client:
        result = client.post('/api/connect', json={'resource': ftdi.URL})
        assert result.status_code == 503 and 'write failed for *IDN?' in result.json()['detail']
        diagnostics = client.get('/api/diagnostics').json()
        assert not diagnostics['connected']
        assert diagnostics['details']['last_command'] == '*IDN?'
        assert any(event['phase'] == 'WRITE_ERROR' for event in diagnostics['details']['events'])
        assert peer.closed


def test_syst_error_usb_write_timeout_is_identified_and_never_resent(usb, monkeypatch):
    peer = UsbPeer(usb.clock)
    original_write = peer.write_data
    def write(raw):
        command = raw.decode().strip()
        if command == ':SYST:ERR?':
            peer.commands.append(command)
            raise FtdiError('UsbError: [Errno 60] Operation timed out') from USBError('timed out', errno=60)
        return original_write(raw)
    monkeypatch.setattr(peer, 'write_data', write)
    usb.peers.append(peer)
    with TestClient(create_app(manager=Manager(provider=VisaProvider()))) as client:
        assert client.post('/api/connect', json={'resource': ftdi.URL, 'clear_status': True}).status_code == 200
        result = client.post('/api/capture', json={'channel': 1})
        assert result.status_code == 503
        assert 'write failed for :SYST:ERR?' in result.json()['detail']
        assert peer.commands.count(':SYST:ERR?') == 1 and peer.closed
        reads = peer.reads
        diagnostics = client.get('/api/diagnostics').json()
        assert diagnostics['details']['last_command'] == ':SYST:ERR?'
        assert any(e['phase'] == 'WRITE_ERROR' and '60' in e['detail'] for e in diagnostics['details']['events'])
        assert peer.reads == reads


def test_quiet_input_drain_reads_stale_bytes_without_hardware_purge(usb):
    peer = UsbPeer(usb.clock)
    peer.pending.extend(b'old reply\n')
    usb.peers.append(peer)
    instrument = ftdi.FtdiInstrument(Connection(resource=ftdi.URL))
    assert peer.purges == 0 and not peer.pending
    assert instrument.diagnostics['events'][0]['detail'].startswith('10 old bytes')
    assert instrument.query('*IDN?').startswith('HAMEG,HMO3524,')
    instrument.close()


@pytest.mark.parametrize('native_timeout', [
    lambda: USBTimeoutError('timed out'),
    lambda: USBError('Operation timed out', errno=60),  # actual macOS report
    lambda: USBError('Operation timed out', errno=110),
    lambda: USBError('Operation timed out', error_code=-7),
])
def test_reads_are_bounded_and_native_usb_timeout_is_reported_as_timeout(usb, monkeypatch, native_timeout):
    peer = UsbPeer(usb.clock)
    usb.peers.append(peer)
    instrument = ftdi.FtdiInstrument(Connection(resource=ftdi.URL, timeout_ms=100))
    with pytest.raises(DeviceError, match='limit'):
        instrument.read_bytes(80001)

    def timeout(count):
        usb.clock.sleep(.11)
        raise FtdiError('USB timeout') from native_timeout()
    monkeypatch.setattr(peer, 'read_data', timeout)
    with pytest.raises(TimeoutError, match='binary bytes'):
        instrument.read_bytes(4)
    assert peer.timeouts[0] <= 101
    instrument.close()


def test_macos_timeout_can_recover_within_deadline_without_resending_query(usb, monkeypatch):
    peer = UsbPeer(usb.clock)
    usb.peers.append(peer)
    instrument = ftdi.FtdiInstrument(Connection(resource=ftdi.URL, timeout_ms=500))
    original_read = peer.read_data
    reads = 0
    def read(count):
        nonlocal reads
        reads += 1
        if reads == 1:
            usb.clock.sleep(.01)
            raise FtdiError('UsbError: [Errno 60] Operation timed out') from USBError('Operation timed out', errno=60)
        return original_read(count)
    monkeypatch.setattr(peer, 'read_data', read)
    assert instrument.query(':SYST:ERR?') == '0,"No error"'
    assert peer.commands == [':SYST:ERR?'] and peer.configurations == 1
    instrument.close()


@pytest.mark.parametrize('failure', [lambda: USBError('gone', errno=19), lambda: USBError('gone', error_code=-4)])
def test_native_disconnect_is_not_treated_as_an_empty_read(usb, monkeypatch, failure):
    peer = UsbPeer(usb.clock)
    usb.peers.append(peer)
    instrument = ftdi.FtdiInstrument(Connection(resource=ftdi.URL))
    def gone(count):
        raise FtdiError('device gone') from failure()
    monkeypatch.setattr(peer, 'read_data', gone)
    with pytest.raises(FtdiError, match='device gone'):
        instrument.query(':SYST:ERR?')
    assert peer.commands == [':SYST:ERR?']
    instrument.close()


def test_explicit_status_clear_precedes_collection_without_polling_error_queue(usb, monkeypatch, tmp_path):
    peer = UsbPeer(usb.clock)
    pending = ['-101,"Invalid character"', '-101,"Invalid character"', '0,"No error"']
    original_write = peer.write_data
    def write(raw):
        if raw.decode().strip() == '*CLS':
            pending.clear()
            peer.answers[':SYST:ERR?'] = '0,"No error"'
        elif raw.decode().strip() == ':SYST:ERR?' and pending:
            peer.answers[':SYST:ERR?'] = pending.pop(0)
        return original_write(raw)
    monkeypatch.setattr(peer, 'write_data', write)
    monkeypatch.setattr(trace, 'log_dir', lambda: tmp_path)
    usb.peers.append(peer)
    with TestClient(create_app(manager=Manager(provider=VisaProvider()))) as client:
        connected = client.post('/api/connect', json={'resource': ftdi.URL, 'trace': True, 'clear_status': True})
        assert connected.status_code == 200
        assert connected.json()['status_cleared'] is True
        assert peer.commands == ['*IDN?', '*CLS']
        assert client.post('/api/capture', json={'channel': 1}).status_code == 200
        assert client.post('/api/action', json={'action': 'run'}).status_code == 200
        assert ':ACQ:STAT RUN' in peer.commands
        assert client.get('/api/status').json()['error'] is None
        assert '*CLS' in next(tmp_path.glob('*.txt')).read_text()


def test_error_after_run_is_retained_without_disconnect_and_success_clears_it(usb, monkeypatch):
    peer = UsbPeer(usb.clock)
    original_write = peer.write_data
    pending = []
    def write(raw):
        command = raw.decode().strip()
        if command == ':ACQ:STAT RUN':
            pending.append('-101,"Invalid character"')
        elif command == ':SYST:ERR?':
            peer.answers[command] = pending.pop(0) if pending else '0,"No error"'
        return original_write(raw)
    monkeypatch.setattr(peer, 'write_data', write)
    usb.peers.append(peer)
    with TestClient(create_app(manager=Manager(provider=VisaProvider()))) as client:
        assert client.post('/api/connect', json={'resource': ftdi.URL}).status_code == 200
        failed = client.post('/api/action', json={'action': 'run'})
        assert failed.status_code == 422 and 'after run' in failed.json()['detail']
        for _ in range(2):
            status = client.get('/api/status').json()
            assert status['connected'] and status['error'] == failed.json()['detail']
        assert client.post('/api/capture', json={'channel': 1}).status_code == 200
        assert client.get('/api/status').json()['error'] is None


def test_connect_does_not_poll_a_nonempty_error_queue(usb):
    peer = UsbPeer(usb.clock)
    peer.answers[':SYST:ERR?'] = '-101,"Invalid character"'
    usb.peers.append(peer)
    backend = VisaProvider().connect(Connection(resource=ftdi.URL))
    assert peer.commands == ['*IDN?'] and not backend.info.get('status_cleared')
    with pytest.raises(ScopeError, match='pending before capture'):
        backend.capture(1)
    assert ':TRAC:DATA?' not in peer.commands
    backend.close()


def test_short_write_and_usb_disconnect_are_not_silently_retried(usb, monkeypatch):
    peer = UsbPeer(usb.clock)
    usb.peers.append(peer)
    instrument = ftdi.FtdiInstrument(Connection(resource=ftdi.URL))
    peer.short_write = True
    with pytest.raises(DeviceError, match='Incomplete'):
        instrument.query('*IDN?')
    peer.short_write = False
    def gone(count):
        raise IOError('USB disconnected')
    monkeypatch.setattr(peer, 'read_data', gone)
    with pytest.raises(IOError, match='disconnected'):
        instrument.read_bytes(1)
    instrument.close()


def test_usb_diagnosis_records_both_dialects_and_clears_comparison_errors(usb, monkeypatch, tmp_path):
    peer = UsbPeer(usb.clock)
    peer.errors = 0
    peer.answers[':HORizontal:MAIN:SCALe?'] = '1e-5'
    original_write = peer.write_data

    def write(raw):
        command = raw.decode().strip()
        if command.startswith(':TIM'):
            peer.errors += 1
        elif command == '*CLS':
            peer.errors = 0
        elif command == ':SYST:ERR?':
            peer.answers[command] = '-101,"Invalid character"' if peer.errors else '0,"No error"'
            peer.errors = max(0, peer.errors - 1)
        return original_write(raw)

    monkeypatch.setattr(peer, 'write_data', write)
    monkeypatch.setattr(trace, 'time', usb.clock)
    monkeypatch.setattr(trace, 'log_dir', lambda: tmp_path)
    usb.peers.append(peer)
    report = VisaProvider().diagnose(Connection(resource=ftdi.URL))
    assert peer.errors == 0 and peer.closed
    failed = {step['command'] for step in report['steps'] if not step['ok']}
    assert failed == {':TIM:SCAL?', ':TIMebase:SCALe?'}
    text = next(tmp_path.glob('*.txt')).read_text()
    assert 'RXB' in text and 'Invalid character' in text and 'PyFtdi HO720 USB' in text


def test_pyftdi_suppressed_usb_timeout_context_recovers_without_resending(usb, monkeypatch):
    peer = UsbPeer(usb.clock)
    usb.peers.append(peer)
    instrument = ftdi.FtdiInstrument(Connection(resource=ftdi.URL, timeout_ms=500))
    read = peer.read_data
    calls = 0
    def wrapped(count):
        nonlocal calls
        calls += 1
        if calls == 1:
            try:
                raise USBError('Operation timed out', errno=60)
            except USBError as exc:
                raise FtdiError(f'UsbError: {exc}') from None
        return read(count)
    monkeypatch.setattr(peer, 'read_data', wrapped)
    assert instrument.query(':SYST:ERR?') == '0,"No error"'
    assert peer.commands == [':SYST:ERR?']
    assert any(e['phase'] == 'USB_READ_TIMEOUT' for e in instrument.diagnostics['events'])
    instrument.close()


def test_binary_bytes_are_preserved_across_a_suppressed_packet_timeout(usb, monkeypatch):
    peer = UsbPeer(usb.clock)
    usb.peers.append(peer)
    instrument = ftdi.FtdiInstrument(Connection(resource=ftdi.URL, timeout_ms=500))
    payload = bytes(range(256)) * 4
    peer.pending.extend(payload)
    read = peer.read_data
    calls = 0
    def wrapped(count):
        nonlocal calls
        assert count == 1  # multi-byte PyFtdi calls may lose accumulated data on timeout
        calls += 1
        if calls == 100:
            try:
                raise USBError('Operation timed out', errno=60)
            except USBError as exc:
                raise FtdiError(f'UsbError: {exc}') from None
        return read(count)
    monkeypatch.setattr(peer, 'read_data', wrapped)
    instrument.timeout = 3000
    assert instrument.read_bytes(len(payload)) == payload
    assert peer.commands == []
    instrument.close()


def test_binary_reads_copy_cached_packets_without_risking_an_accumulated_prefix(usb, monkeypatch):
    peer = UsbPeer(usb.clock)
    usb.peers.append(peer)
    instrument = ftdi.FtdiInstrument(Connection(resource=ftdi.URL, timeout_ms=500))
    payload = bytes(range(256)) * 4
    packets = iter(payload[i:i+64] for i in range(0,len(payload),64))
    peer._readbuffer, peer._readoffset = bytearray(), 0
    counts, failures = [], 0
    def read(count):
        nonlocal failures
        counts.append(count)
        available = len(peer._readbuffer)-peer._readoffset
        if not available:
            assert count == 1
            if len(counts) == 3 and failures == 0:
                failures += 1
                try:
                    raise USBError('Operation timed out', errno=60)
                except USBError as exc:
                    raise FtdiError(f'UsbError: {exc}') from None
            peer._readbuffer, peer._readoffset = bytearray(next(packets)), 0
        else:
            assert count <= available  # cannot advance into another USB packet
        result=bytes(peer._readbuffer[peer._readoffset:peer._readoffset+count])
        peer._readoffset += len(result)
        return result
    monkeypatch.setattr(peer,'read_data',read)
    assert instrument.read_bytes(len(payload)) == payload
    assert failures == 1 and 63 in counts and len(counts) < len(payload)//10
    instrument.close()
