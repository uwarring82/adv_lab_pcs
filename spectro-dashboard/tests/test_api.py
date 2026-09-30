"""HTTP-level tests: validation errors become 4xx responses, CSV stays consistent."""
import pytest
from fastapi.testclient import TestClient

from spectro.app import create_app
from spectro.backend.sim_backend import SimulatedSpectrometer


@pytest.fixture
def client():
    app = create_app(backend=SimulatedSpectrometer(seed=0, realtime=False))
    with TestClient(app) as c:
        yield c


def test_invalid_config_is_422_and_not_applied(client):
    assert client.post("/api/config", json={"scans_to_average": 1_000_000}).status_code == 422
    r = client.post("/api/config", json={"boxcar_width": 1024})
    assert r.status_code == 422 and "boxcar_width" in r.json()["detail"]
    assert client.get("/api/config").json()["boxcar_width"] == 0


def test_spectrum_csv_has_one_row_per_channel_at_max_boxcar(client):
    client.post("/api/config", json={"boxcar_width": 1023}).raise_for_status()
    lines = client.get("/api/spectrum.csv").text.strip().splitlines()
    rows = [line for line in lines if not line.startswith("#")][1:]  # drop comments + header
    assert len(rows) == 2048


def test_histogram_parameter_errors_are_422(client):
    assert client.get("/api/measurement/histogram", params={"channel": 5}).status_code == 404
    client.post("/api/measurement", json={"num_scans": 20}).raise_for_status()
    for params in ({"channel": 600, "bins": "0"}, {"channel": 600, "bins": "bogus"},
                   {"channel": 600, "bins": "1000000"}, {"channel": 600, "bins": "-3"},
                   {"channel": 99999}):
        r = client.get("/api/measurement/histogram", params=params)
        assert r.status_code == 422, (params, r.status_code, r.text)
    r = client.get("/api/measurement/histogram", params={"channel": 600, "bins": "12"})
    assert len(r.json()["counts"]) == 12


def test_dark_notice_on_exposure_change(client):
    client.post("/api/dark").raise_for_status()
    client.post("/api/config", json={"subtract_dark": True}).raise_for_status()
    r = client.post("/api/config", json={"integration_time_ms": 50}).json()
    assert r["subtract_dark"] is False and r["notice"]
    assert client.post("/api/config", json={"subtract_dark": True}).status_code == 422


def test_web_page_is_revalidated_after_updates(client):
    for path in ("/", "/app.js", "/lib/uPlot.iife.min.js"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
    assert "Spectrometer Dashboard" in client.get("/").text


def test_measurement_ids_and_websocket(client):
    a = client.post("/api/measurement", json={"num_scans": 3}).json()
    b = client.post("/api/measurement", json={"num_scans": 3}).json()
    assert b["id"] == a["id"] + 1 == client.get("/api/measurement").json()["id"]
    with client.websocket_connect("/ws/stream") as ws:
        frame = ws.receive_json()
    assert len(frame["intensities"]) == len(frame["wavelengths"]) == len(frame["sem"]) == 2048
