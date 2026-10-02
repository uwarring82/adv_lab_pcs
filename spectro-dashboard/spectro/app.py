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
from .diagnostics import collect as collect_diagnostics
from .models import ConfigUpdate, Histogram, Measurement, MeasurementRequest, Spectrum

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


def create_app(prefer_sim: bool = False, backend: SpectrometerBackend | None = None) -> FastAPI:
    mgr = AcquisitionManager(prefer_sim=prefer_sim, backend=backend)

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
            [f"model={s['model']}", f"timestamp={s['timestamp']}", f"config={s['config']}"],
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
        rows = ((i, f"{wl:.4f}", f"{mu:.4f}", f"{e:.4f}")
                for i, (wl, mu, e) in enumerate(zip(m["wavelengths"], m["mean"], m["sem"], strict=True)))
        return _csv_response(
            [f"model={m['model']}", f"timestamp={m['timestamp']}",
             f"num_scans={m['num_scans']}", f"config={m['config']}"],
            ["channel", "wavelength_nm", "mean_counts", "sem_counts"], rows, "measurement.csv")

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
