<#
.SYNOPSIS
    Builds the legacy Tk fallback Windows executable.

.DESCRIPTION
    This script builds the Tk-based UI (ui.py) as a standalone Windows
    executable using PyInstaller. This is the LEGACY fallback build —
    the primary Electron + React portable app is built via the
    primary Electron build script (scripts\build_portable_electron.ps1).

    The Tk fallback is kept for users who prefer the original
    standard-library Tk/ttk interface. It is NOT the default or
    recommended build for new users.

    To build the Electron portable app instead, run:
        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_portable_electron.ps1

    Output: dist\OBS Overlay Import Utility.exe (Tk fallback)
#>

$ErrorActionPreference = "Stop"

function Assert-LastExit([string] $Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Venv = Join-Path $Root ".venv-build"
$Python = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $Python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $Venv
        Assert-LastExit "Creating the build environment"
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $Venv
        Assert-LastExit "Creating the build environment"
    }
    else {
        throw "Python 3.10 or newer was not found."
    }
}

& $Python -m pip install --upgrade pip
Assert-LastExit "Updating pip"
& $Python -m pip install -e "$Root[build]"
Assert-LastExit "Installing build dependencies"
& $Python -m unittest discover -s (Join-Path $Root "tests") -v
Assert-LastExit "Automated tests"

$PortableApp = Join-Path $Root "dist\OBS Overlay Import Utility.exe"
if (Test-Path $PortableApp) {
    try {
        Remove-Item -LiteralPath $PortableApp -Force -ErrorAction Stop
    }
    catch {
        throw "Close OBS Overlay Import Utility before rebuilding it. The current executable is still in use."
    }
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --manifest (Join-Path $Root "scripts\app.manifest") `
    --name "OBS Overlay Import Utility" `
    --paths (Join-Path $Root "src") `
    --collect-data "obs_overlay_import_utility" `
    --distpath (Join-Path $Root "dist") `
    --workpath (Join-Path $Root "build") `
    --specpath $Root `
    (Join-Path $Root "tools\launcher.py")
Assert-LastExit "Portable application build"

Write-Host "Tk fallback app created at:"
Write-Host $PortableApp
Write-Host ""
Write-Host "NOTE: This is the legacy Tk fallback build."
Write-Host "For the Electron + React portable app, run:"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_portable_electron.ps1"
