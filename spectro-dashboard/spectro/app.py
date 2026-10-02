"""FastAPI application: dashboard + REST + WebSocket + CSV.

The same server provides the student-facing HTTP API. Interactive, auto-generated
API docs are available at /docs (Swagger UI) and /redoc.
"""
from __future__ import annotations

import asyncio
import csv
import io
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .acquisition import AcquisitionError, AcquisitionManager, Busy
from .backend import SpectrometerBackend
from .calibration import CalibrationError, CalibrationStore, check_coefficients, compare, fit_lines
from .diagnostics import collect as collect_diagnostics
from .diagnostics import windows_usb_devices
from .driver import DriverError
from .driver import install as install_driver
from .models import (
    CalibrationPreview, CalibrationRequest, ConfigUpdate, Histogram, Measurement,
    MeasurementRequest, Spectrum)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _csv_response(comments: list[str], header: list[str], rows, filename: str) -> StreamingResponse:
    buf = io.StringIO()
    for c in comments:
        buf.write(f"# {c}\n")
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})


def _calibration_comment(mgr: AcquisitionManager) -> str:
    c = mgr.calibration_info()
    coeffs = c["custom_coefficients"] or c["factory_coefficients"]
    return (f"wavelength_calibration={c['active']}: lambda(p) = c0 + c1 p + c2 p^2 + c3 p^3, "
            f"c = [{', '.join(f'{x:.10g}' for x in coeffs)}]")


def create_app(prefer_sim: bool = False, backend: SpectrometerBackend | None = None,
               calibration_file: str | Path | None = None) -> FastAPI:
    """``calibration_file``: where custom wavelength calibrations are saved
    (None keeps them in memory only, e.g. for tests)."""
    mgr = AcquisitionManager(prefer_sim=prefer_sim, backend=backend,
                             calibration_store=CalibrationStore(calibration_file))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        mgr.close()  # release the device on shutdown

    app = FastAPI(
        lifespan=lifespan,
        title="Ocean Optics Spectrometer Dashboard",
        description=(
            "Live control, preview, and data access for an Ocean Optics USB "
            "spectrometer. Quick start: `GET /api/spectrum` returns one spectrum "
            "as JSON; `POST /api/measurement` takes N raw scans and returns the "
            "per-channel mean and standard error; `GET /api/measurement/histogram` "
            "gives the intensity histogram of one channel. Every data endpoint has "
            "a CSV twin. List index = channel number."
        ),
        version=__version__,
    )
    app.state.mgr = mgr

    # Invalid requests -> 422 with a readable message; device busy -> 409.
    @app.exception_handler(AcquisitionError)
    async def _invalid(request: Request, exc: AcquisitionError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(Busy)
    async def _busy(request: Request, exc: Busy):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CalibrationError)
    async def _bad_calibration(request: Request, exc: CalibrationError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(DriverError)
    async def _no_driver_install(request: Request, exc: DriverError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    # --- REST: info & control --------------------------------------------
    @app.get("/api/health", tags=["info"])
    def health():
        return {"status": "ok"}

    @app.get("/api/status", tags=["info"])
    def status():
        return {"info": mgr.info(), "config": mgr.get_config()}

    @app.get("/api/diagnostics", tags=["info"])
    def diagnostics():
        """Why no spectrometer is used, with next steps (`hints`): which seabreeze
        backend loads, which devices it sees and, on Windows, each Ocean Optics USB
        device with its driver. Takes a few seconds on Windows."""
        return collect_diagnostics(mgr)

    @app.post("/api/reconnect", tags=["info"])
    def reconnect():
        """Look for the spectrometer again, e.g. after closing another program that
        used it. Switching from the simulator to hardware resets settings, dark
        spectrum and measurement."""
        return mgr.reconnect()

    @app.post("/api/driver/install", tags=["info"])
    def driver_install():
        """Windows: download Ocean Optics' signed WinUSB driver (fixed version,
        checksum verified) and install it for the connected spectrometer. Windows
        asks for administrator approval. Then call /api/reconnect."""
        return install_driver(windows_usb_devices())

    # --- REST: wavelength calibration ------------------------------------
    @app.get("/api/calibration", tags=["calibration"])
    def get_calibration():
        """Active calibration ('factory' or 'custom'), both polynomials, and their
        comparison on the reference lines (residuals, RMS, largest difference)."""
        return mgr.calibration_info()

    @app.post("/api/calibration", tags=["calibration"])
    def set_calibration(req: CalibrationRequest):
        """Use a custom calibration: `coefficients` c0..c3, or a fit to reference
        `lines` (pixel, wavelength_nm). Saved for this device."""
        lines = [l.model_dump() for l in req.lines] if req.lines else None
        return mgr.set_calibration(coefficients=req.coefficients, lines=lines, order=req.order)

    @app.delete("/api/calibration", tags=["calibration"])
    def reset_calibration():
        """Back to the factory calibration stored in the spectrometer."""
        return mgr.reset_calibration()

    @app.post("/api/calibration/preview", tags=["calibration"])
    def preview_calibration(req: CalibrationPreview):
        """Fit reference lines and compare the fit with `reference` coefficients,
        without changing the calibration in use (practice with example spectra)."""
        reference = check_coefficients(req.reference, req.pixels)
        fit = fit_lines([(l.pixel, l.wavelength_nm) for l in req.lines], req.pixels, req.order)
        return {"coefficients": fit["coefficients"], "order": fit["order"],
                "comparison": compare(reference, fit["coefficients"], fit["lines"], req.pixels)}

    @app.get("/api/config", tags=["control"])
    def get_config():
        return mgr.get_config()

    @app.post("/api/config", tags=["control"])
    def set_config(update: ConfigUpdate):
        return mgr.update_config(**update.model_dump(exclude_none=True))

    @app.post("/api/dark", tags=["control"])
    def store_dark():
        return mgr.store_dark()

    @app.delete("/api/dark", tags=["control"])
    def clear_dark():
        return mgr.clear_dark()

    # --- REST: live data --------------------------------------------------
    @app.get("/api/spectrum", response_model=Spectrum, tags=["live"])
    def get_spectrum():
        """Acquire one live spectrum (mean +- SEM over `scans_to_average` scans)."""
        return mgr.acquire()

    @app.get("/api/spectrum.csv", tags=["live"])
    def get_spectrum_csv():
        """Acquire one live spectrum and return it as CSV."""
        s = mgr.acquire()
        rows = ((i, f"{wl:.4f}", f"{m:.4f}", f"{e:.4f}")
                for i, (wl, m, e) in enumerate(zip(s["wavelengths"], s["intensities"], s["sem"], strict=True)))
        return _csv_response(
            [f"model={s['model']}", f"timestamp={s['timestamp']}", f"config={s['config']}",
             _calibration_comment(mgr)],
            ["channel", "wavelength_nm", "intensity_counts", "sem_counts"], rows, "spectrum.csv")

    # --- REST: statistical measurement -----------------------------------
    @app.post("/api/measurement", response_model=Measurement, tags=["measurement"])
    def run_measurement(req: MeasurementRequest):
        """Take `num_scans` raw scans and return per-channel mean and SEM.
        Blocks until done (num_scans x integration time, at most 30 min); poll
        `/api/measurement/progress` from another client to follow it. Returns 409
        if another measurement is running."""
        return mgr.measure(req.num_scans)

    @app.get("/api/measurement", response_model=Measurement, tags=["measurement"])
    def get_measurement():
        """The most recent measurement."""
        m = mgr.measurement_summary()
        if m is None:
            raise HTTPException(404, "No measurement yet: POST /api/measurement first.")
        return m

    @app.get("/api/measurement/progress", tags=["measurement"])
    def measurement_progress():
        return mgr.progress()

    @app.get("/api/measurement/histogram", response_model=Histogram, tags=["measurement"])
    def measurement_histogram(channel: int, bins: str = "auto"):
        """Intensity histogram of one channel over the scans of the last measurement.
        `bins` is a number (1-1000) or a numpy rule: auto, fd, doane, scott, stone,
        rice, sturges, sqrt."""
        h = mgr.histogram(channel, int(bins) if bins.isdigit() else bins)
        if h is None:
            raise HTTPException(404, "No measurement yet: POST /api/measurement first.")
        return h

    @app.get("/api/measurement.csv", tags=["measurement"])
    def measurement_csv():
        """The most recent measurement as CSV (channel, wavelength, mean, SEM)."""
        m = mgr.measurement_summary()
        if m is None:
            raise HTTPException(404, "No measurement yet: POST /api/measurement first.")
        header = ["channel", "wavelength_nm", "mean_counts", "sem_counts"]
        cols = [m["wavelengths"], m["mean"], m["sem"]]
        if m["dark_subtracted"]:  # also the raw values and the dark spectrum used
            header += ["raw_mean_counts", "raw_sem_counts", "dark_counts", "dark_sem_counts"]
            cols += [m["raw_mean"], m["raw_sem"], m["dark"], m["dark_sem"]]
        rows = ((i, *(f"{v:.4f}" for v in values)) for i, values in enumerate(zip(*cols, strict=True)))
        return _csv_response(
            [f"model={m['model']}", f"timestamp={m['timestamp']}",
             f"num_scans={m['num_scans']}", f"config={m['config']}",
             f"dark_subtracted={m['dark_subtracted']}"
             + (f" (dark: mean of {m['dark_scans']} scans)" if m["dark_subtracted"] else ""),
             _calibration_comment(mgr)],
            header, rows, "measurement.csv")

    # --- WebSocket: live stream ------------------------------------------
    @app.websocket("/ws/stream")
    async def stream(ws: WebSocket):
        await ws.accept()
        try:
            while True:
                # Acquire off the event loop so the blocking hardware call does
                # not stall the server; the integration time paces the loop.
                try:
                    spectrum = await asyncio.to_thread(mgr.acquire)
                except Busy:  # a measurement has the device; resume afterwards
                    await asyncio.sleep(0.5)
                    continue
                await ws.send_json(spectrum)
                await asyncio.sleep(0.01)
        except WebSocketDisconnect:
            pass
        except Exception:
            await ws.close()

    # --- Dashboard (static) ----------------------------------------------
    # Make browsers revalidate the page and scripts (cheap 304s), so an updated
    # .exe never runs with a cached page from the previous version.
    @app.middleware("http")
    async def _revalidate_web(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    else:
        @app.get("/", response_class=HTMLResponse)
        def _missing():
            return "<h1>web/ not found</h1><p>See /docs for the API.</p>"

    return app
