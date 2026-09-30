# Configuration for the Ocean Optics classic-series Windows setup package.
# Edit values here; Install.ps1 and Verify.ps1 read this file.
@{
    # USB Vendor ID for Ocean Optics / Ocean Insight classic-series spectrometers
    # (Flame-S/T, USB2000/+, USB4000, HR2000/+, HR4000, Maya, QE, NIRQuest, ...).
    # All enumerate under VID_2457; each model has its own PID.
    VendorId = '2457'

    # --- Driver source -------------------------------------------------------
    # 'Vendor'    : only run installers you dropped in .\vendor (OceanView etc.)
    # 'Seabreeze' : only the open-source path (Python + python-seabreeze drivers)
    # 'Both'      : run vendor installers if present, then the Seabreeze path
    # 'None'      : skip driver install, do OS/USB tweaks + verify only
    DriverSource = 'Both'

    # Installers to run from .\vendor (proprietary; you supply the file).
    # Silent switches are best-effort and installer-specific: verify them once,
    # then fill in here. Leave empty to have the script just list what it finds.
    #   OceanView is an install4j package: silent flag is usually  -q
    #   (optionally  -dir "C:\Program Files\Ocean Optics\OceanView").
    VendorInstallers = @(
        # @{ File = 'OceanView-2.0.8-win64.exe'; Args = '-q' }
    )

    # --- Open-source (python-seabreeze) path --------------------------------
    InstallPythonIfMissing = $true
    WingetPythonId         = 'Python.Python.3.12'
    PythonEnvPath          = 'C:\ProgramData\OceanOptics\venv'  # shared, off user profile

    # --- Power management ----------------------------------------------------
    DisableUsbSelectiveSuspend  = $true   # global active power plan
    DisablePerDevicePowerSaving = $true   # per-device (device must be plugged in; see Verify.ps1)
    SetHighPerformancePlan      = $false  # flip to $true for a dedicated/permanent lab PC

    # --- Housekeeping --------------------------------------------------------
    LogDir = 'C:\ProgramData\OceanOptics\logs'
}
