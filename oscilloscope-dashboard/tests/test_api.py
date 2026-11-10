import csv
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import numpy as np
import pytest
from fastapi.testclient import TestClient

from scope.app import create_app
from scope.backends import DeviceError, Simulator
from scope.manager import Manager


@pytest.fixture
def client():
    with TestClient(create_app(simulated=True)) as c:
        yield c


def test_static_and_status(client):
    assert client.get("/api/status").json()["info"]["simulated"]
    for path in ("/", "/app.js", "/style.css", "/lib/uPlot.iife.min.js", "/docs", "/openapi.json"):
        assert client.get(path).status_code == 200


def test_capture_statistics_and_csv_are_same_snapshot(client):
    data = client.post("/api/capture", json={"channel": 2}).json()
    assert data["info"]["simulated"] is True
    assert data["channel"] == 2 and data["points"] == 1200
    volts = np.array(data["voltage_v"])
    assert data["rms_v"] == pytest.approx(np.sqrt(np.mean(volts ** 2)))
    response = client.get(f"/api/capture/{data['id']}/csv")
    rows = list(csv.reader(io.StringIO(response.text)))
    assert ["# simulated", "True"] in rows
    assert rows[6] == ["time_s", "CH2_voltage_v"]
    np.testing.assert_array_equal(np.array(rows[7:], dtype=float)[:, 1], volts)
    assert client.get("/api/status").json()["last_capture_id"] == data["id"]
    client.post("/api/capture", json={"channel": 1})
    assert client.get(f"/api/capture/{data['id']}/csv").status_code == 409


def test_settings_and_stop_freeze_simulator(client):
    assert client.post("/api/settings", json={"timebase_s": 0.002, "scale_v": 0.5, "coupling": "AC"}).status_code == 200
    state = client.get("/api/settings").json()
    assert state["timebase_s"] == 0.002 and state["scale_v"] == 0.5
    client.post("/api/action", json={"action": "stop"})
    a = client.post("/api/capture", json={"channel": 1}).json()
    b = client.post("/api/capture", json={"channel": 1}).json()
    assert a["voltage_v"] == b["voltage_v"]
    client.post("/api/action", json={"action": "run"})
    c = client.post("/api/capture", json={"channel": 1}).json()
    assert b["voltage_v"] != c["voltage_v"]


@pytest.mark.parametrize("path,body", [
    ("settings", {"timebase_s": -1}), ("settings", {"scale_v": 0}),
    ("settings", {"scale_v": "NaN"}), ("settings", {"timebase_s": "inf"}),
    ("settings", {"coupling": "DC;*RST"}), ("settings", {}),
    ("capture", {"channel": 5}), ("capture", {"channel": 0}),
    ("action", {"action": "reset"}), ("action", {"action": "run", "command": "*RST"}),
    ("connect", {"resource": "ASRL3::INSTR", "timeout_ms": 30001}),
])
def test_invalid_requests_leave_state_unchanged(client, path, body):
    before = client.get("/api/settings").json()
    assert client.post(f"/api/{path}", json=body).status_code == 422
    assert client.get("/api/settings").json() == before


def test_real_mode_never_silently_simulates():
    with TestClient(create_app()) as client:
        assert client.get("/api/status").json()["connected"] is False
        assert client.post("/api/capture", json={"channel": 1}).status_code == 422
        client.post("/api/simulator", json={})
        assert client.get("/api/status").json()["info"]["simulated"]


def test_disconnect_invalidates_saved_capture(client):
    data = client.post("/api/capture", json={"channel": 1}).json()
    client.post("/api/disconnect", json={})
    assert not client.get("/api/status").json()["connected"]
    assert client.get(f"/api/capture/{data['id']}/csv").status_code == 409


def test_failed_discovery_preserves_active_simulator(client):
    def unavailable():
        raise DeviceError("VISA unavailable")
    client.app.state.manager.provider.resources = unavailable
    assert client.get("/api/resources").status_code == 503
    assert client.get("/api/status").json()["info"]["simulated"] is True
    assert client.post("/api/capture", json={"channel": 1}).status_code == 200


def test_cross_origin_control_rejected(client):
    assert client.post("/api/action", json={"action": "run"}, headers={"Origin": "https://example.org"}).status_code == 403
    assert client.post("/api/action", json={"action": "run"}, headers={"Origin": "http://testserver"}).status_code == 200
    assert client.get("/api/status", headers={"Host": "example.org"}).status_code == 400


def test_model_channel_limit(client):
    client.app.state.manager.backend.info["channels"] = 2
    assert client.post("/api/capture", json={"channel": 3}).status_code == 422
    assert client.post("/api/settings", json={"channel": 3, "scale_v": 1}).status_code == 422


def test_transport_failure_disconnects_and_releases_device(client):
    class Broken(Simulator):
        closed = False

        def capture(self, channel):
            raise TimeoutError("Timed out")

        def close(self):
            self.closed = True

    backend = Broken()
    client.app.state.manager.backend = backend
    assert client.post("/api/capture", json={"channel": 1}).status_code == 503
    assert backend.closed
    state = client.get("/api/status").json()
    assert not state["connected"] and "Timed out" in state["error"]
    client.post("/api/simulator", json={})
    assert client.post("/api/capture", json={"channel": 1}).status_code == 200


def test_overlapping_capture_controls_and_disconnect_are_rejected():
    entered, release = Event(), Event()

    class Gated(Simulator):
        def capture(self, channel):
            entered.set()
            assert release.wait(5)
            return super().capture(channel)

    mgr = Manager()
    mgr.backend = Gated()
    with TestClient(create_app(manager=mgr)) as client, ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, "/api/capture", json={"channel": 1})
        try:
            assert entered.wait(3)
            for path, body in [("capture", {"channel": 1}), ("action", {"action": "run"}),
                               ("disconnect", {}), ("simulator", {})]:
                assert client.post(f"/api/{path}", json=body).status_code == 409
            assert client.get("/api/health").status_code == 200
        finally:
            release.set()
        assert future.result().status_code == 200
