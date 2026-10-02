"""Hardware diagnostics: why is no spectrometer used, and what to do about it.

Collected on demand (GET /api/diagnostics, the badge in the dashboard, and the
console at start-up), so that a tester can send one block of text instead of
answering questions about drivers and Device Manager.
"""
from __future__ import annotations

import base64
import json
import logging
import platform
import subprocess
import sys
import warnings

from . import __version__
from .driver import devices_needing_driver

VENDOR_ID = "2457"  # Ocean Optics classic-series USB vendor ID

# Lists present USB devices with the Ocean Optics vendor ID and their driver.
# Runs as a normal user; passed with -EncodedCommand to avoid quoting problems.
_PS_USB_QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
$keys = 'DEVPKEY_Device_Service', 'DEVPKEY_Device_DriverProvider', 'DEVPKEY_Device_DriverVersion', 'DEVPKEY_Device_DriverInfPath'
$list = @(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_@VID@' } | ForEach-Object {
    $p = @{}
    Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName $keys | ForEach-Object { $p[$_.KeyName] = $_.Data }
    [pscustomobject]@{
        name            = $_.FriendlyName
        status          = $_.Status
        class           = $_.Class
        instance_id     = $_.InstanceId
        service         = $p['DEVPKEY_Device_Service']
        driver_provider = $p['DEVPKEY_Device_DriverProvider']
        driver_version  = $p['DEVPKEY_Device_DriverVersion']
        inf             = $p['DEVPKEY_Device_DriverInfPath']
    }
})
ConvertTo-Json -InputObject $list -Compress
""".replace("@VID@", VENDOR_ID)


def windows_usb_devices() -> list[dict] | dict | None:
    """Ocean Optics USB devices Windows knows, with their driver; None off Windows,
    or {"error": ...} if the query failed."""
    if sys.platform != "win32":
        return None
    encoded = base64.b64encode(_PS_USB_QUERY.encode("utf-16-le")).decode("ascii")
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = out.stdout.strip()
        if out.returncode != 0 or not text:
            return {"error": f"PowerShell exit code {out.returncode}: {out.stderr.strip()[:300]}"}
        devices = json.loads(text)
        return devices if isinstance(devices, list) else [devices]
    except Exception as exc:  # no PowerShell, timeout, unexpected output
        return {"error": f"{type(exc).__name__}: {exc}"}


def probe_seabreeze() -> dict:
    """Which seabreeze backend loads (and why the compiled one may not), and the
    devices it lists. Only call while the app is not using the hardware itself."""
    out = {"version": None, "backend": None, "backend_messages": [], "devices": None, "error": None}
    messages: list[str] = []

    class _Collect(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    handler = _Collect(level=logging.WARNING)
    logger = logging.getLogger("seabreeze")
    logger.addHandler(handler)
    try:
        import seabreeze
        out["version"] = getattr(seabreeze, "__version__", None)
        from seabreeze.backends import get_backend
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            backend = get_backend()
        messages.extend(str(w.message) for w in caught)
        out["backend"] = backend.__name__.rsplit(".", 1)[-1]
        import seabreeze.spectrometers as sb
        out["devices"] = [str(d) for d in sb.list_devices()]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        logger.removeHandler(handler)
        out["backend_messages"] = messages
    return out


def hints(report: dict) -> list[str]:
    """Plain-language next steps derived from a diagnostics report."""
    spec = report["spectrometer"]
    if not spec["simulated"]:
        return [f"The spectrometer is in use: {spec['model']}. Nothing to fix."]
    if spec.get("forced_simulator"):
        return ["The dashboard was started with --sim, so the simulator is used on purpose."]

    out: list[str] = []
    sb = report.get("seabreeze") or {}
    if sb.get("error") or not sb.get("backend"):
        if report.get("frozen"):
            out.append("The app's hardware backend (python-seabreeze) could not be loaded "
                       f"({sb.get('error')}). This is a problem of the app itself: please report "
                       "this text.")
        else:
            out.append("python-seabreeze is not available in this Python environment "
                       f"({sb.get('error')}). Install it with: pip install seabreeze")
        return out
    if sb["backend"] != "cseabreeze":
        out.append(f"seabreeze could not load its main backend and uses {sb['backend']!r} "
                   "instead, which usually finds no device on Windows. Please report this text.")

    usb = report.get("usb_devices")
    if isinstance(usb, dict):
        out.append(f"Could not ask Windows for USB devices: {usb.get('error')}")
    elif usb == []:
        out.append("Windows does not see any Ocean Optics USB device (vendor ID 2457). Check "
                   "the cable, and plug the spectrometer directly into the PC. Newer Ocean "
                   "models (ST, SR and HR series) use vendor ID 0999 and are not supported.")
    elif usb:
        for dev in usb:
            name = dev.get("name") or dev.get("instance_id")
            service = (dev.get("service") or "").strip()
            if dev.get("status") != "OK":
                out.append(f"Windows reports status '{dev.get('status')}' for '{name}': it has no "
                           "working driver. Click 'Install driver' (Windows asks for "
                           "administrator approval), then 'Retry hardware'. Manual steps: see "
                           "the lab setup guide.")
            elif service.lower() != "winusb":
                out.append(f"'{name}' uses the driver '{service or 'unknown'}' "
                           f"({dev.get('driver_provider') or 'unknown provider'}). The dashboard "
                           "needs Ocean Optics' WinUSB driver; older Ocean software installs a "
                           "different one (e.g. Jungo WinDriver, 'windrvr6'). Click 'Install "
                           "driver' (administrator approval), then 'Retry hardware'. This may "
                           "affect older Ocean software on this PC.")

    if sb.get("devices"):
        out.append(f"seabreeze sees {', '.join(sb['devices'])} but the dashboard could not open "
                   f"it ({spec.get('fallback_reason')}). Most likely another program, such as "
                   "OceanView, is using it: close that program, then click 'Retry hardware'.")
    elif usb and not out:
        out.append("Windows lists the spectrometer with a WinUSB driver, but seabreeze does not "
                   "find it. Close other programs that may use it (e.g. OceanView), unplug and "
                   "replug it, then click 'Retry hardware'. If that does not help, the driver "
                   "may come from newer Ocean software: reinstall it with "
                   "windows/ocean-optics-setup/Install.ps1, and please report this text.")
    if usb is None and not out:
        out.append("No spectrometer found. Check the USB connection; on Linux, install the "
                   "udev rules with seabreeze_os_setup.")
    return out


def collect(mgr) -> dict:
    info = mgr.info()
    report = {
        "app_version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "spectrometer": {
            "simulated": info["simulated"],
            "forced_simulator": mgr.forced_sim,
            "model": info["model"],
            "serial": info["serial"],
            "fallback_reason": info["fallback_reason"],
        },
        # Probe seabreeze only while the hardware is not in use by the app.
        "seabreeze": probe_seabreeze() if info["simulated"] and not mgr.forced_sim else None,
        "usb_devices": windows_usb_devices(),
    }
    report["driver_install_available"] = bool(devices_needing_driver(report["usb_devices"]))
    report["hints"] = hints(report)
    return report
