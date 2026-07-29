<#
.SYNOPSIS
    Builds the primary Electron + React Windows portable executable.

.DESCRIPTION
    Uses a dedicated repository-local Python environment for every backend
    packaging step, then packages already-built Electron output. The legacy Tk
    fallback remains scripts/build_portable_tk.ps1.

.PARAMETER CleanDependencies
    Explicitly remove desktop\node_modules before npm ci. Use only when the
    dependency tree is known to be stale or incompatible with this platform.
#>
[CmdletBinding()]
param(
    [switch]$CleanDependencies
)

$ErrorActionPreference = "Stop"

function Assert-LastExit([string] $Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

function Resolve-BootstrapPython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @("py", "-3")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    throw "Python 3.10 or newer was not found."
}

function Install-ElectronDependencies([string] $DesktopPath, [bool] $RemoveExisting) {
    $NodeModules = Join-Path $DesktopPath "node_modules"
    if ($RemoveExisting -and (Test-Path -LiteralPath $NodeModules)) {
        Write-Host "Removing Electron dependencies because -CleanDependencies was specified..."
        try {
            Remove-Item -LiteralPath $NodeModules -Recurse -Force -ErrorAction Stop
        }
        catch {
            throw "Could not remove $NodeModules. Close only the application or terminal using this repository, then rerun with -CleanDependencies. $($_.Exception.Message)"
        }
    }

    Write-Host "Installing Electron dependencies from the lockfile..."
    Push-Location $DesktopPath
    try {
        & npm ci
        Assert-LastExit "Installing Electron dependencies"
    }
    finally {
        Pop-Location
    }
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Desktop = Join-Path $Root "desktop"
$BuildVenv = Join-Path $Root ".venv-build-electron"
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $BuildPython)) {
    $BootstrapPython = Resolve-BootstrapPython
    $BootstrapArgs = @($BootstrapPython | Select-Object -Skip 1) + @("-m", "venv", $BuildVenv)
    Write-Host "Creating dedicated Electron build environment at $BuildVenv..."
    & $BootstrapPython[0] @BootstrapArgs
    Assert-LastExit "Creating Electron build environment"
}

& $BuildPython -m pip install --upgrade pip
Assert-LastExit "Upgrading build-environment pip"
& $BuildPython -m pip install -e "$Root[build]"
Assert-LastExit "Installing Python build dependencies"

# This is consumed by desktop/scripts/package-backend.cjs. Do not mutate a
# shell-global Python setting: the package step receives this one explicit path.
$env:OBS_OVERLAY_BUILD_PYTHON = $BuildPython

Install-ElectronDependencies $Desktop $CleanDependencies.IsPresent
Push-Location $Desktop
try {
    & npm run package:all
    Assert-LastExit "Electron portable application build"
}
finally {
    Pop-Location
    Remove-Item Env:OBS_OVERLAY_BUILD_PYTHON -ErrorAction SilentlyContinue
}

$PortableApp = Join-Path $Desktop "release\OBS Overlay Import Utility Electron Portable.exe"
if (-not (Test-Path -LiteralPath $PortableApp)) {
    throw "Electron portable executable was not created at $PortableApp."
}

Write-Host "Electron portable app created at:"
Write-Host $PortableApp
