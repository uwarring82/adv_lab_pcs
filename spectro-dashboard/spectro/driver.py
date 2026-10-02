"""Install Ocean Optics' WinUSB driver for a connected spectrometer (Windows only).

Students' laptops show the spectrometer as "Ocean Optics USB2000+" with Code 28
(no driver). The driver package used here is the one python-seabreeze's
seabreeze_os_setup installs: Ocean Optics' WHQL-signed OOI_*.inf/.cat files. It
is downloaded from a fixed commit and checked against a SHA-256 before anything
is installed; only the .inf files matching the connected devices are installed,
with pnputil in an elevated process (Windows asks for administrator approval).
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DRIVER_ZIP_URL = ("https://raw.githubusercontent.com/ap--/python-seabreeze/"
                  "3313d157f40edaae1903789e8a061f6bc3e44745/os_support/windows-driver-files.zip")
DRIVER_ZIP_SHA256 = "46a6d1aba32e3b76db5ea7a4fc908cd8b99d9e87e2021c93113be2372706e378"

ERROR_CANCELLED = 1223        # the user declined the administrator prompt
PNPUTIL_OK = {0, 259, 3010}   # success, nothing left to update, success + reboot needed

# Elevated part: pnputil for each .inf, output to a log file.
_INSTALL_PS = r"""
$log = '@LOG@'
$code = 0
foreach ($inf in @(@INFS@)) {
    "> pnputil /add-driver $inf /install" | Out-File -FilePath $log -Append -Encoding utf8
    & pnputil.exe /add-driver $inf /install 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0 -and $code -eq 0) { $code = $LASTEXITCODE }
}
exit $code
"""

# Unelevated part: start the script above with "Run as administrator" and wait.
_ELEVATE_PS = r"""
try {
    $p = Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -Wait -PassThru `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', '"@SCRIPT@"')
    exit $p.ExitCode
} catch {
    exit @CANCELLED@
}
"""


class DriverError(RuntimeError):
    """The driver cannot be installed (not Windows, no device, download problem)."""


def hardware_id(instance_id: str) -> str | None:
    m = re.search(r"VID_[0-9A-F]{4}&PID_[0-9A-F]{4}", instance_id or "", re.IGNORECASE)
    return m.group(0).upper() if m else None


def devices_needing_driver(usb_devices) -> list[dict]:
    """Ocean Optics devices without a working WinUSB driver."""
    if not isinstance(usb_devices, list):
        return []
    return [d for d in usb_devices
            if d.get("status") != "OK" or (d.get("service") or "").lower() != "winusb"]


def matching_infs(folder: Path, hardware_ids) -> list[Path]:
    """The package's .inf files for these hardware IDs (Windows XP variants skipped)."""
    out = []
    for inf in sorted(Path(folder).glob("*.inf")):
        if inf.stem.upper().endswith("_XP"):
            continue
        text = inf.read_text(encoding="latin-1").upper()
        if any(h in text for h in hardware_ids):
            out.append(inf)
    return out


def download_package(dest: Path, url: str = DRIVER_ZIP_URL, sha256: str = DRIVER_ZIP_SHA256) -> Path:
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
    except OSError as exc:
        raise DriverError(f"Could not download the driver package ({exc}). "
                          "Check the internet connection.") from exc
    if hashlib.sha256(data).hexdigest() != sha256:
        raise DriverError("The downloaded driver package has an unexpected checksum; "
                          "nothing was installed.")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            parts = Path(name.replace("\\", "/")).parts
            if name.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
                raise DriverError("Unsafe file name in the driver package; nothing was installed.")
        z.extractall(dest)
    return Path(dest)


def _ps_quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def install(usb_devices) -> dict:
    """Download, verify and install the driver for the connected Ocean Optics devices."""
    if sys.platform != "win32":
        raise DriverError("Installing the driver from the dashboard is only possible on Windows.")
    need = devices_needing_driver(usb_devices)
    if not need:
        raise DriverError("No connected Ocean Optics device without a working driver was found. "
                          "Plug the spectrometer in, then check again.")
    hwids = sorted({h for d in need if (h := hardware_id(d.get("instance_id", "")))})

    work = Path(tempfile.mkdtemp(prefix="ocean-driver-"))
    folder = download_package(work / "drivers")
    infs = matching_infs(folder, hwids)
    if not infs:
        raise DriverError(f"The driver package contains no driver for {', '.join(hwids)}.")

    log = work / "pnputil.log"
    script = work / "install.ps1"
    script.write_text(_INSTALL_PS.replace("@LOG@", str(log).replace("'", "''"))
                      .replace("@INFS@", ", ".join(_ps_quote(i) for i in infs)),
                      encoding="utf-8-sig")  # BOM: Windows PowerShell 5.1 reads it as UTF-8
    outer = _ELEVATE_PS.replace("@SCRIPT@", str(script)).replace("@CANCELLED@", str(ERROR_CANCELLED))
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", base64.b64encode(outer.encode("utf-16-le")).decode("ascii")],
        capture_output=True, text=True, timeout=600,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    code = proc.returncode
    text = log.read_text(encoding="utf-8-sig", errors="replace") if log.exists() else ""
    result = {"installed": code in PNPUTIL_OK, "reboot_required": code == 3010, "exit_code": code,
              "drivers": [i.name for i in infs], "hardware_ids": hwids, "log": text[-4000:],
              "reason": None}
    if code == ERROR_CANCELLED:
        result["reason"] = "Administrator approval was declined; nothing was installed."
    elif code not in PNPUTIL_OK:
        result["reason"] = f"pnputil reported exit code {code}; see the log."
    return result
