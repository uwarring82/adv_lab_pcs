"""One owner of the instrument; reject overlapping requests instead of queueing."""
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from threading import Lock

from .backends import Busy, DeviceError, ScopeError, Simulator, VisaProvider


class Manager:
    def __init__(self, simulated=False, provider=None):
        self.provider = provider or VisaProvider()
        self.backend = Simulator() if simulated else None
        self.lock = Lock()
        self.last = None
        self.sequence = 0
        self.error = None

    @contextmanager
    def access(self, invalidate=True):
        if not self.lock.acquire(blocking=False):
            raise Busy("Oscilloscope busy. Wait for the current operation to finish.")
        try:
            yield
        except DeviceError as exc:
            if invalidate:
                self._drop()
            self.error = str(exc)
            raise
        except ScopeError:
            raise
        except Exception as exc:
            if invalidate:
                self._drop()
            self.error = f"Instrument communication failed: {exc}. Check the cable, VISA driver and serial settings, then reconnect."
            raise DeviceError(self.error) from exc
        finally:
            self.lock.release()

    def _drop(self):
        backend, self.backend = self.backend, None
        self.last = None
        if backend:
            with suppress(Exception):
                backend.close()

    def require(self, channel=None):
        if self.backend is None:
            raise ScopeError("No oscilloscope connected. Select a resource or start the simulator.")
        if channel is not None and not 1 <= channel <= self.backend.info["channels"]:
            raise ScopeError(f"This model has {self.backend.info['channels']} channels.")
        return self.backend

    def status(self):
        with self.access():
            return {"connected": self.backend is not None,
                    "info": self.backend.info.copy() if self.backend else None,
                    "error": self.error,
                    "last_capture_id": self.last["id"] if self.last else None}

    def resources(self):
        with self.access(invalidate=False):
            return {"resources": self.provider.resources()}

    def connect(self, req=None):
        with self.access():
            self._drop()
            self.error = None
            self.backend = self.provider.connect(req) if req else Simulator()
            return self.backend.info.copy()

    def disconnect(self):
        with self.access():
            self._drop()
            self.error = None
        return {"connected": False}

    def settings(self, channel):
        with self.access():
            return self.require(channel).settings(channel)

    def configure(self, req):
        with self.access():
            b = self.require(req.channel)
            b.configure(req)
            return b.settings(req.channel)

    def action(self, action):
        with self.access():
            self.require().action(action)
            return {"action": action, "sent": True}

    def capture(self, channel):
        with self.access():
            b = self.require(channel)
            data = b.capture(channel)
            self.sequence += 1
            data.update(id=self.sequence, channel=channel, info=b.info.copy(),
                        captured_at=datetime.now(timezone.utc).isoformat(), mode="screen_preview")
            self.last = data
            return data

    def saved(self, capture_id):
        with self.access():
            if not self.last or self.last["id"] != capture_id:
                raise Busy("This capture is no longer available. Capture again or export the displayed data from the dashboard.")
            return self.last

    def close(self):
        with self.lock:
            self._drop()
            self.provider.close()
