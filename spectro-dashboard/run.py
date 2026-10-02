"""Entry point: start the local server and open the dashboard in a browser.

This is what the packaged .exe runs. Usage:
    python run.py                # real hardware, falls back to simulator
    python run.py --sim          # force the simulator (no hardware needed)
    python run.py --no-browser   # do not auto-open a browser
    python run.py --port 8777
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

# A windowed PyInstaller build has no console: stdout/stderr are None and
# uvicorn's logging would crash. Send output to a log file instead.
if sys.stdout is None or sys.stderr is None:
    _log = open(Path(tempfile.gettempdir()) / "spectrometer-dashboard.log", "a", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

import uvicorn  # noqa: E402  (after the stdout fix above)

from spectro.app import create_app  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Ocean Optics spectrometer dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8777)
    p.add_argument("--sim", action="store_true", help="Force the simulated spectrometer")
    p.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    args = p.parse_args()

    app = create_app(prefer_sim=args.sim)
    url = f"http://{args.host}:{args.port}/"

    if not args.no_browser:
        def _open():
            time.sleep(1.2)  # give uvicorn a moment to bind
            try:
                webbrowser.open(url)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    mgr = app.state.mgr
    info = mgr.info()
    print(f"\n  Spectrometer dashboard:  {url}")
    print(f"  Student API docs:        {url}docs")
    if not info["simulated"]:
        print(f"  Spectrometer:            {info['model']} (serial {info['serial']})\n")
    elif mgr.forced_sim:
        print("  Spectrometer:            SIMULATOR (started with --sim)\n")
    else:
        # Make the reason visible where testers look first.
        print("  Spectrometer:            none found -> using the SIMULATOR")
        print(f"  Reason:                  {info['fallback_reason']}")
        print(f"  Details and next steps:  click the SIMULATED badge, or open {url}api/diagnostics\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
