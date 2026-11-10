"""Run on the instrument PC; defaults to loopback port 8778."""
import argparse
import threading
import webbrowser

import uvicorn

from scope import __version__
from scope.app import create_app


def main():
    parser = argparse.ArgumentParser(description="RIGOL / HAMEG oscilloscope dashboard")
    parser.add_argument("--version", action="version", version=f"Oscilloscope Dashboard {__version__}")
    parser.add_argument("--sim", action="store_true", help="Start with synthetic waveforms")
    parser.add_argument("--port", type=int, default=8778)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--visa-library", default=None, help="VISA library path or @py for PyVISA-py")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Oscilloscope Dashboard {__version__}\nDashboard: {url}\nStudent API: {url}docs")
    print("SIMULATOR: synthetic data" if args.sim else "Select a USB or serial resource in the dashboard.")
    if not args.no_browser:
        timer = threading.Timer(1.2, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    uvicorn.run(create_app(args.sim, args.visa_library), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
