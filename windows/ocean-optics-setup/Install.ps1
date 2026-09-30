<#
.SYNOPSIS
    Prepare a Windows 11 machine for an Ocean Optics / Ocean Insight classic-series
    USB spectrometer: OS checks, USB power tweaks, and driver install.

.DESCRIPTION
    Idempotent and safe to re-run. Self-elevates to administrator, logs a full
    transcript, and runs these stages:
        1. Environment checks (admin, OS, architecture)
        2. USB power tweaks (disable selective suspend; optional High Performance plan)
        3. Driver install per config (vendor installers and/or python-seabreeze)
        4. Device check (Verify.ps1)

    Any failed step stops the script with exit code 1; "Done" is printed only when
    every step succeeded. A spectrometer that is not plugged in yet is not an
    error: plug it in and run Verify.ps1 afterwards.

.PARAMETER DriverSource
    Override config: Vendor | Seabreeze | Both | None

.PARAMETER SkipPowerTweaks
    Skip the USB power management stage.

.PARAMETER NoElevate
    Do not attempt self-elevation (assume already admin, e.g. when called by another script).

.PARAMETER Relaunched
    Internal: set on the elevated copy so its window stays open at the end.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Install.ps1 -DriverSource Seabreeze
#>
[CmdletBinding()]
param(
    [ValidateSet('Vendor', 'Seabreeze', 'Both', 'None')]
    [string]$DriverSource,
    [switch]$SkipPowerTweaks,
    [switch]$NoElevate,
    [switch]$Relaunched
)

$ErrorActionPreference = 'Stop'

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# --- Self-elevate, forwarding the same parameters and the exit code ----------
if (-not $NoElevate -and -not (Test-Admin)) {
    Write-Host 'Not elevated; relaunching as administrator...'
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Relaunched')
    foreach ($kv in $PSBoundParameters.GetEnumerator()) {
        if ($kv.Value -is [switch]) {
            if ($kv.Value.IsPresent) { $argList += "-$($kv.Key)" }
        }
        else {
            $argList += "-$($kv.Key)"; $argList += "$($kv.Value)"
        }
    }
    $p = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $argList -Wait -PassThru
    exit $p.ExitCode
}

# --- Load configuration ------------------------------------------------------
$Here = Split-Path -Parent $PSCommandPath
$cfg = Import-PowerShellDataFile (Join-Path $Here 'config.psd1')
if ($PSBoundParameters.ContainsKey('DriverSource')) { $cfg.DriverSource = $DriverSource }

New-Item -ItemType Directory -Force -Path $cfg.LogDir | Out-Null
$log = Join-Path $cfg.LogDir ("install-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date))
Start-Transcript -Path $log | Out-Null

function Write-Stage { param($m) Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Write-Ok    { param($m) Write-Host "[ ok ] $m" -ForegroundColor Green }
function Write-Skip  { param($m) Write-Host "[skip] $m" -ForegroundColor DarkGray }
function Write-Warn2 { param($m) Write-Host "[warn] $m" -ForegroundColor Yellow }

# Windows PowerShell does not stop on a failing native command, even with
# $ErrorActionPreference = 'Stop', so check the exit code of each one.
function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$What,
        [Parameter(Mandatory)][scriptblock]$Command,
        [int[]]$OkCodes = @(0)
    )
    $global:LASTEXITCODE = 0
    & $Command | Out-Host
    if ($OkCodes -notcontains $LASTEXITCODE) {
        throw "$What failed (exit code $LASTEXITCODE)."
    }
}

# The Microsoft Store alias in WindowsApps is not a real interpreter (exit 9009).
function Find-Python {
    Get-Command python -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notlike '*\WindowsApps\*' } |
        Select-Object -First 1
}

$exitCode = 0
try {
    # === 1. Environment checks ==============================================
    Write-Stage '1. Environment checks'
    $os = Get-CimInstance Win32_OperatingSystem
    Write-Host ("OS         : {0} (build {1})" -f $os.Caption, $os.BuildNumber)
    Write-Host ("Architecture: {0}" -f $os.OSArchitecture)
    Write-Host ("Computer   : {0}" -f $env:COMPUTERNAME)
    Write-Host ("Admin      : {0}" -f (Test-Admin))
    Write-Host ("Config     : DriverSource={0}" -f $cfg.DriverSource)
    if (-not [Environment]::Is64BitOperatingSystem) {
        Write-Warn2 'Non-64-bit OS detected; classic-series x64 drivers expect 64-bit Windows.'
    }
    Write-Ok 'Checks complete.'

    # === 2. USB power tweaks ================================================
    if ($SkipPowerTweaks) {
        Write-Skip 'USB power tweaks (per -SkipPowerTweaks).'
    }
    else {
        Write-Stage '2. USB power management'

        # Pick the plan first: USB settings are stored per plan, so changing plans
        # afterwards would bring back that plan's own selective-suspend setting.
        if ($cfg.SetHighPerformancePlan) {
            # Optional: not every machine ships the High Performance scheme.
            powercfg /SETACTIVE 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c 2>$null
            if ($LASTEXITCODE -eq 0) { Write-Ok 'Activated High Performance power plan.' }
            else { Write-Warn2 'High Performance plan not available on this machine.' }
        }

        if ($cfg.DisableUsbSelectiveSuspend) {
            # SUB_USB = 2a737441-..., USB selective suspend = 48e6b7a6-...
            $sub = '2a737441-1930-4402-8d77-b2bebba308a3'
            $set = '48e6b7a6-50f5-4782-a5d4-53bb8f07e226'
            Invoke-Native 'Disabling USB selective suspend (AC)' { powercfg /SETACVALUEINDEX SCHEME_CURRENT $sub $set 0 }
            Invoke-Native 'Disabling USB selective suspend (DC)' { powercfg /SETDCVALUEINDEX SCHEME_CURRENT $sub $set 0 }
            Invoke-Native 'Re-applying the active power plan' { powercfg /SETACTIVE SCHEME_CURRENT }
            Write-Ok 'USB selective suspend disabled on the active power plan.'
            Write-Host 'Note: this is a per-plan setting; re-run Install.ps1 after switching power plans.'
        }
        Write-Host 'Note: per-device power saving is applied in Verify.ps1 (device must be present).'
    }

    # === 3. Driver install ==================================================
    Write-Stage "3. Driver install ($($cfg.DriverSource))"

    # Returns the number of installers run; throws if one fails.
    function Install-VendorDrivers {
        $vendorDir = Join-Path $Here 'vendor'
        $found = Get-ChildItem -Path $vendorDir -Filter *.exe -File -ErrorAction SilentlyContinue
        if (-not $found) {
            Write-Warn2 "No installers found in $vendorDir. See vendor\README.md."
            return 0
        }
        if (-not $cfg.VendorInstallers -or $cfg.VendorInstallers.Count -eq 0) {
            Write-Warn2 'Installers present but none listed in config.VendorInstallers.'
            Write-Host  'Found on disk:'
            $found | ForEach-Object { Write-Host "   - $($_.Name)" }
            Write-Host  'Add each to config.psd1 (File + silent Args), or run it by hand once.'
            return 0
        }
        $ran = 0
        foreach ($item in $cfg.VendorInstallers) {
            $path = Join-Path $vendorDir $item.File
            if (-not (Test-Path $path)) { throw "Vendor installer listed in config.psd1 is missing: $($item.File)" }
            Write-Host "Running $($item.File) $($item.Args) ..."
            $p = Start-Process -FilePath $path -ArgumentList $item.Args -Wait -PassThru
            switch ($p.ExitCode) {
                0       { Write-Ok "$($item.File) completed." }
                3010    { Write-Warn2 "$($item.File) completed; a reboot is required." }
                1641    { Write-Warn2 "$($item.File) completed and started a reboot." }
                default { throw "$($item.File) failed (exit code $($p.ExitCode)); check its own log." }
            }
            $ran++
        }
        return $ran
    }

    function Install-SeabreezeDrivers {
        $py = Find-Python
        if (-not $py) {
            if (-not $cfg.InstallPythonIfMissing) {
                throw 'Python 3 not found and InstallPythonIfMissing is off; install Python, then re-run.'
            }
            if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
                throw 'Python 3 and winget are both missing; install Python 3 manually, then re-run.'
            }
            Write-Host "Installing Python via winget ($($cfg.WingetPythonId))..."
            # -1978335189 = 0x8A15002B: already installed, no newer version.
            Invoke-Native "winget install $($cfg.WingetPythonId)" -OkCodes @(0, -1978335189) -Command {
                winget install --id $cfg.WingetPythonId -e --silent `
                    --accept-source-agreements --accept-package-agreements
            }
            # Refresh PATH for this session
            $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                        [Environment]::GetEnvironmentVariable('Path', 'User')
            $py = Find-Python
            if (-not $py) { throw 'Python was installed but is not on PATH yet; open a new shell and re-run.' }
        }
        Write-Host "Using Python: $($py.Source)"

        $venv = $cfg.PythonEnvPath
        $vpy = Join-Path $venv 'Scripts\python.exe'
        if (-not (Test-Path $vpy)) {
            Write-Host "Creating venv at $venv ..."
            New-Item -ItemType Directory -Force -Path (Split-Path $venv) | Out-Null
            Invoke-Native 'Creating the Python venv' { & $py.Source -m venv $venv }
            if (-not (Test-Path $vpy)) { throw "venv creation reported success but $vpy is missing." }
        }
        Write-Host 'Installing python-seabreeze stack (needs internet)...'
        Invoke-Native 'Upgrading pip' { & $vpy -m pip install --upgrade pip }
        $reqs = Join-Path $Here 'requirements-spectrometer.txt'
        if (Test-Path $reqs) {
            # Pinned to the known-good lab environment (seabreeze 2.10.1 + pyusb).
            Invoke-Native 'pip install -r requirements-spectrometer.txt' { & $vpy -m pip install -r $reqs }
        }
        else {
            Invoke-Native 'pip install seabreeze pyusb' { & $vpy -m pip install --upgrade seabreeze pyusb }
        }
        Write-Host 'Installing Ocean Optics USB drivers via seabreeze_os_setup...'
        $setup = Join-Path $venv 'Scripts\seabreeze_os_setup.exe'
        if (Test-Path $setup) {
            Invoke-Native 'seabreeze_os_setup' { & $setup }
        }
        else {
            Invoke-Native 'seabreeze os_setup' { & $vpy -c 'import seabreeze.os_setup as s; s.main()' }
        }
        Write-Ok 'Seabreeze drivers installed.'
    }

    switch ($cfg.DriverSource) {
        'Vendor' {
            if ((Install-VendorDrivers) -eq 0) {
                throw 'DriverSource is Vendor but no vendor installer ran; see vendor\README.md.'
            }
        }
        'Seabreeze' { Install-SeabreezeDrivers }
        'Both'      { $null = Install-VendorDrivers; Install-SeabreezeDrivers }
        'None'      { Write-Skip 'Driver install (DriverSource=None).' }
    }

    # === 4. Device check ====================================================
    Write-Stage '4. Device check'
    & (Join-Path $Here 'Verify.ps1') -NoElevate
    switch ($LASTEXITCODE) {
        0       { Write-Ok 'Spectrometer found and a test spectrum acquired.' }
        2       { Write-Warn2 'No spectrometer connected yet: plug it in and run Verify.ps1.' }
        3       { Write-Warn2 'Spectrometer enumerates but was not tested with software (no seabreeze venv).' }
        default { throw 'A spectrometer is connected but the device check failed (see above).' }
    }

    Write-Host "`nDone. Full log: $log" -ForegroundColor Cyan
}
catch {
    $exitCode = 1
    Write-Host "`n[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace
    Write-Host "Setup did NOT complete. Full log: $log" -ForegroundColor Red
}
finally {
    Stop-Transcript | Out-Null
    if ($Relaunched) { Read-Host 'Press Enter to close this window' | Out-Null }
}
exit $exitCode
