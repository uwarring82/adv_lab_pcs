<#
.SYNOPSIS
    Build the single-file OscilloscopeDashboard.exe with PyInstaller (run on Windows).

.DESCRIPTION
    Creates a build venv, installs the app + PyInstaller, runs the tests, and bundles:
      - the web/ dashboard assets,
      - PyVISA and PyVISA-py backends and serial support.
    VISA runtimes and hardware drivers must already be installed on the PC.
    Output: dist\OscilloscopeDashboard.exe. Exits 1 if any step fails.
#>
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'

# Windows PowerShell does not stop on a failing native command, even with
# $ErrorActionPreference = 'Stop', so check the exit code of each one.
function Invoke-Native {
    param([Parameter(Mandatory)][string]$What, [Parameter(Mandatory)][scriptblock]$Command)
    $global:LASTEXITCODE = 0
    & $Command | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)  # oscilloscope-dashboard\
$exe = Join-Path $root 'dist\OscilloscopeDashboard.exe'
$started = Get-Date
Push-Location $root
try {
    $venv = Join-Path $root '.build-venv'
    $py = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $py)) {
        Invoke-Native 'Creating the build venv' { & $Python -m venv $venv }
    }
    Invoke-Native 'Upgrading pip' { & $py -m pip install --upgrade pip }
    Invoke-Native 'Installing requirements' { & $py -m pip install -r (Join-Path $root 'requirements-dev.txt') }
    # Quoted: an unquoted >= is a redirection in PowerShell.
    Invoke-Native 'Installing PyInstaller' { & $py -m pip install 'pyinstaller>=6.3' }
    if (-not $SkipTests) {
        Invoke-Native 'Tests' { & $py -m pytest -q }
    }

    Invoke-Native 'PyInstaller' {
        & $py -m PyInstaller `
            --noconfirm --clean --onefile --console `
            --name OscilloscopeDashboard `
            --add-data 'web;web' `
            --collect-all pyvisa `
            --collect-all pyvisa_py `
            --collect-all serial `
            --collect-submodules uvicorn `
            --hidden-import uvicorn.loops.auto `
            --hidden-import uvicorn.protocols.http.auto `
            --hidden-import uvicorn.protocols.websockets.auto `
            --hidden-import uvicorn.lifespan.on `
            run.py
    }

    $built = Get-Item $exe -ErrorAction SilentlyContinue
    if (-not $built -or $built.LastWriteTime -lt $started) {
        throw "PyInstaller finished but $exe was not (re)built."
    }

    # The .exe redistributes the bundled Python packages: ship their licenses with it.
    # (Lists every package in the build venv, a superset of what PyInstaller bundled.)
    $licenses = Join-Path $root 'dist\THIRD_PARTY_LICENSES.txt'
    Invoke-Native 'Installing pip-licenses' { & $py -m pip install 'pip-licenses>=5' }
    Invoke-Native 'Collecting third-party licenses' {
        & $py -m piplicenses --with-license-file --no-license-path --format=plain-vertical --output-file $licenses
    }
    Copy-Item (Join-Path $root '..\LICENSE') (Join-Path $root 'dist\LICENSE.txt')
    Copy-Item (Join-Path $root '..\THIRD_PARTY_NOTICES.md') (Join-Path $root 'dist\THIRD_PARTY_NOTICES.md')
    foreach ($file in 'README-TEST-DE.txt', 'Start-Rigol.cmd', 'Simulator.cmd') {
        Copy-Item (Join-Path $root "packaging\$file") (Join-Path $root "dist\$file")
    }

    Write-Host "`nBuilt: $exe ($([math]::Round($built.Length / 1MB, 1)) MB)" -ForegroundColor Green
    Write-Host 'Distribute it together with dist\LICENSE.txt, THIRD_PARTY_NOTICES.md and THIRD_PARTY_LICENSES.txt.'
}
catch {
    Write-Host "`n[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
