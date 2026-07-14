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

Write-Host "Portable app created at:"
Write-Host $PortableApp
