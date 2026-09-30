<#
.SYNOPSIS
    Verify an Ocean Optics classic-series spectrometer is enumerated and ready.

.DESCRIPTION
    Run this WITH THE SPECTROMETER PLUGGED IN. It:
        1. Lists USB devices under VID_2457 with status and hardware IDs
           (the hardware ID reveals the exact model, e.g. PID_101E = USB2000+,
           PID_1022 = USB4000).
        2. Disables per-device USB power saving (needs the device present + admin).
        3. If the python-seabreeze venv exists, opens the device with seabreeze
           and acquires one spectrum as an end-to-end check.

    Exit codes: 0 = device found and a spectrum acquired, 2 = no device connected,
    1 = device connected but not usable (driver status or seabreeze check failed),
    3 = device enumerates but was not tested with software (no seabreeze venv).

.PARAMETER NoElevate
    Do not attempt self-elevation (Install.ps1 calls it this way).

.PARAMETER Relaunched
    Internal: set on the elevated copy so its window stays open at the end.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Verify.ps1
#>
[CmdletBinding()]
param([switch]$NoElevate, [switch]$Relaunched)

$ErrorActionPreference = 'Continue'

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}
if (-not $NoElevate -and -not (Test-Admin)) {
    $p = Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Relaunched')
    exit $p.ExitCode
}

function Write-Ok    { param($m) Write-Host "[ ok ] $m" -ForegroundColor Green }
function Write-Warn2 { param($m) Write-Host "[warn] $m" -ForegroundColor Yellow }
function Write-Fail  { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }

function Exit-Verify {
    param([int]$Code)
    $label = @{ 0 = 'device working'; 1 = 'device NOT usable'; 2 = 'no device connected';
                3 = 'device enumerates, NOT tested with software' }[$Code]
    Write-Host "`nVerification done: $label (exit code $Code)." -ForegroundColor Cyan
    if ($Relaunched) { Read-Host 'Press Enter to close this window' | Out-Null }
    exit $Code
}

$Here = Split-Path -Parent $PSCommandPath
$cfg = Import-PowerShellDataFile (Join-Path $Here 'config.psd1')
$vid = $cfg.VendorId

Write-Host "`n=== USB devices under VID_$vid ===" -ForegroundColor Cyan
$devs = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
          Where-Object { $_.InstanceId -match "VID_$vid" })

if ($devs.Count -eq 0) {
    Write-Warn2 "No VID_$vid device present. Plug the spectrometer into a direct port and re-run."
    Write-Host  "If it shows as 'Unknown device', the driver did not bind -> re-run Install.ps1."
    Exit-Verify 2
}

$ok = $true        # nothing has failed so far
$tested = $false   # set once software has actually acquired a spectrum
foreach ($d in $devs) {
    Write-Host ("`nStatus      : {0}" -f $d.Status)
    Write-Host ("FriendlyName: {0}" -f $d.FriendlyName)
    Write-Host ("Class       : {0}" -f $d.Class)
    Write-Host ("InstanceId  : {0}" -f $d.InstanceId)
    try {
        $hw = (Get-PnpDeviceProperty -InstanceId $d.InstanceId `
                -KeyName 'DEVPKEY_Device_HardwareIds' -ErrorAction Stop).Data
        Write-Host  'HardwareIds :'
        $hw | ForEach-Object { Write-Host "   $_" }
    } catch { }
    if ($d.Status -eq 'OK') { Write-Ok 'Device enumerated cleanly.' }
    else { Write-Fail "Device status is '$($d.Status)' (expected 'OK'): the driver is not working."; $ok = $false }
}

# --- Per-device power saving (a warning, not a failure) -----------------------
if ($cfg.DisablePerDevicePowerSaving) {
    Write-Host "`n=== Per-device power saving ===" -ForegroundColor Cyan
    try {
        $pm = Get-CimInstance -Namespace root\wmi -ClassName MSPower_DeviceEnable `
                -ErrorAction Stop | Where-Object { $_.InstanceName -like "*VID_$vid*" }
        if (-not $pm) { Write-Host 'No matching power-management node (some devices expose none).' }
        foreach ($e in $pm) {
            if ($e.Enable) {
                $e.Enable = $false
                Set-CimInstance -InputObject $e -ErrorAction Stop
                Write-Ok "Disabled 'let the computer turn off this device' for $($e.InstanceName)"
            }
            else { Write-Host "Already disabled for $($e.InstanceName)" }
        }
    } catch { Write-Warn2 "Could not adjust per-device power mgmt: $($_.Exception.Message)" }
}

# --- End-to-end python-seabreeze check ------------------------------------
$vpy = Join-Path $cfg.PythonEnvPath 'Scripts\python.exe'
if (Test-Path $vpy) {
    Write-Host "`n=== python-seabreeze check ===" -ForegroundColor Cyan
    # Run from a file: Windows PowerShell 5.1 strips double quotes from native arguments.
    $test = Join-Path $env:TEMP 'ocean-optics-verify.py'
    Set-Content -Path $test -Encoding ASCII -Value @'
import math
import sys
import seabreeze.spectrometers as sb

devices = sb.list_devices()
print("devices:", devices)
if not devices:
    sys.exit("seabreeze sees no spectrometer")
spec = sb.Spectrometer(devices[0])
try:
    wl = spec.wavelengths()
    lo, hi = spec.integration_time_micros_limits
    spec.integration_time_micros(min(max(100_000, lo), hi))
    counts = spec.intensities(correct_dark_counts=False, correct_nonlinearity=False)
    if len(counts) != len(wl):
        sys.exit(f"malformed spectrum: {len(counts)} values for {len(wl)} wavelengths")
    if not all(math.isfinite(c) for c in counts):
        sys.exit("malformed spectrum: contains NaN or infinite values")
    print("model:", spec.model, "| serial:", spec.serial_number, "| pixels:", len(wl))
    print(f"test spectrum: {min(counts):.0f} .. {max(counts):.0f} counts")
finally:
    spec.close()
'@
    & $vpy $test
    if ($LASTEXITCODE -eq 0) { $tested = $true; Write-Ok 'seabreeze acquired a spectrum.' }
    else {
        $ok = $false
        Write-Fail 'seabreeze could not open the device. If it shows in Device Manager but'
        Write-Fail 'seabreeze finds nothing, the WinUSB/libusb driver binding may be wrong'
        Write-Fail '(pyseabreeze backend + Zadig WinUSB is the fallback). See README.'
    }
}
else {
    Write-Warn2 "python-seabreeze venv not found at $($cfg.PythonEnvPath): the device could not be"
    Write-Warn2 'tested with software. Run Install.ps1 -DriverSource Seabreeze (or Both) to test end to end.'
}

if (-not $ok) { Exit-Verify 1 }
elseif (-not $tested) { Exit-Verify 3 }
else { Exit-Verify 0 }
