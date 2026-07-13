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
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "OBS Overlay Import Utility" `
    --paths (Join-Path $Root "src") `
    --distpath (Join-Path $Root "dist") `
    --workpath (Join-Path $Root "build") `
    --specpath $Root `
    (Join-Path $Root "tools\launcher.py")
Assert-LastExit "Portable application build"

Write-Host "Portable app created at:"
Write-Host (Join-Path $Root "dist\OBS Overlay Import Utility.exe")
