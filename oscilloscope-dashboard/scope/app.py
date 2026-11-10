"""Local dashboard and documented student API."""
import csv
import io
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .backends import ScopeError, VisaProvider
from .manager import Manager
from .models import Action, Capture, Connection, Settings

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(simulated=False, visa_library=None, manager=None):
    mgr = manager or Manager(simulated, VisaProvider(visa_library))

    @asynccontextmanager
    async def lifespan(app):
        yield
        mgr.close()

    app = FastAPI(title="Oscilloscope Dashboard", version=__version__, lifespan=lifespan,
                  description="Local RIGOL/HAMEG control. Captures are single-channel screen previews in seconds and volts.")
    app.state.manager = mgr
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        # No cross-origin control from a website opened alongside the dashboard.
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and (
                request.headers.get("sec-fetch-site") == "cross-site" or
                (origin and origin != str(request.base_url).rstrip("/"))):
            return JSONResponse({"detail": "Control requests must come from this dashboard's origin."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ScopeError)
    async def scope_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/status")
    def status():
        return mgr.status()

    @app.get("/api/resources")
    def resources():
        return mgr.resources()

    @app.post("/api/connect")
    def connect(req: Connection):
        return mgr.connect(req)

    @app.post("/api/simulator")
    def simulator():
        return mgr.connect()

    @app.post("/api/disconnect")
    def disconnect():
        return mgr.disconnect()

    @app.get("/api/settings")
    def settings(channel: int = Query(default=1, ge=1, le=4)):
        return mgr.settings(channel)

    @app.post("/api/settings")
    def configure(req: Settings):
        return mgr.configure(req)

    @app.post("/api/action")
    def action(req: Action):
        return mgr.action(req.action)

    @app.post("/api/capture")
    def capture(req: Capture):
        return mgr.capture(req.channel)

    @app.get("/api/capture/{capture_id}/csv")
    def export(capture_id: int):
        """Export an existing capture. Never triggers a new acquisition."""
        data = mgr.saved(capture_id)
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        for key, value in (("capture_id", data["id"]), ("captured_at", data["captured_at"]),
                           ("model", data["info"]["model"]), ("serial", data["info"]["serial"]),
                           ("simulated", data["info"]["simulated"]), ("mode", data["mode"])):
            writer.writerow(["# " + key, value])
        writer.writerow(["time_s", f"CH{data['channel']}_voltage_v"])
        writer.writerows(zip(data["time_s"], data["voltage_v"], strict=True))
        return Response(out.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="oscilloscope-{capture_id}.csv"'})

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
