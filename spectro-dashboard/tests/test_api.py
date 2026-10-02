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


def test_diagnostics_and_reconnect_endpoints(client):
    r = client.get("/api/diagnostics").json()
    assert r["spectrometer"]["simulated"] is True and r["hints"]
    assert {"app_version", "python", "platform", "frozen", "seabreeze", "usb_devices"} <= r.keys()
    rc = client.post("/api/reconnect").json()
    assert set(rc) >= {"connected"}


def test_calibration_endpoints(client):
    info = client.get("/api/calibration").json()
    assert info["active"] == "factory" and len(info["factory_coefficients"]) == 4
    lines = [{"pixel": 100, "wavelength_nm": 375.0}, {"pixel": 1000, "wavelength_nm": 680.0}]
    r = client.post("/api/calibration", json={"lines": lines})
    assert r.status_code == 200 and r.json()["active"] == "custom"
    assert client.get("/api/spectrum").json()["wavelengths"][1000] == pytest.approx(680.0)
    assert "wavelength_calibration=custom" in client.get("/api/spectrum.csv").text
    bad = client.post("/api/calibration", json={"lines": [{"pixel": 5, "wavelength_nm": 400}]})
    assert bad.status_code == 422 and "At least 2" in bad.json()["detail"]
    assert client.delete("/api/calibration").json()["active"] == "factory"


def test_measurement_csv_with_dark_has_raw_and_dark_columns(client):
    client.post("/api/config", json={"scans_to_average": 3}).raise_for_status()
    client.post("/api/dark").raise_for_status()
    client.post("/api/config", json={"subtract_dark": True}).raise_for_status()
    m = client.post("/api/measurement", json={"num_scans": 4}).json()
    assert m["dark_subtracted"] is True and len(m["dark"]) == len(m["mean"])
    lines = client.get("/api/measurement.csv").text.splitlines()
    assert any(l.startswith("# dark_subtracted=True") for l in lines)
    header = next(l for l in lines if not l.startswith("#"))
    assert header == ("channel,wavelength_nm,mean_counts,sem_counts,"
                      "raw_mean_counts,raw_sem_counts,dark_counts,dark_sem_counts")


def test_driver_install_off_windows_is_a_clear_422(client, monkeypatch):
    import spectro.driver as driver
    monkeypatch.setattr(driver.sys, "platform", "darwin")
    r = client.post("/api/driver/install")
    assert r.status_code == 422 and "Windows" in r.json()["detail"]


def test_example_spectra_are_served(client):
    index = client.get("/examples/index.json").json()
    assert len(index) >= 5 and {"id", "file", "title", "description", "calibration"} <= index[0].keys()
    for e in index:
        lines = client.get(f"/examples/{e['file']}").text.splitlines()
        rows = [l for l in lines if not l.startswith("#")]
        assert rows[0] == "channel,wavelength_nm,mean_counts,sem_counts,std_counts"
        assert len(rows) - 1 == 2048, e["file"]


def test_calibration_preview_does_not_change_the_device(client):
    r = client.post("/api/calibration/preview", json={
        "lines": [{"pixel": 50.6, "wavelength_nm": 404.656}, {"pixel": 217.21, "wavelength_nm": 435.833},
                  {"pixel": 842.03, "wavelength_nm": 546.074}],
        "reference": [395.4, 0.1897, -1.231e-5, -5.2e-10], "pixels": 2048}).json()
    assert r["order"] == 2 and r["comparison"]["factory_rms_nm"] > 0.1
    assert client.get("/api/calibration").json()["active"] == "factory"


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
