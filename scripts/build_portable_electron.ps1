<#
.SYNOPSIS
    Builds the primary Electron + React Windows portable executable.

.DESCRIPTION
    Builds the standalone Python JSON-lines backend, the React renderer, and
    Electron main/preload code, then packages them with electron-builder's
    Windows portable target.

    This is the primary customer artifact. It does not package or run the Tk
    launcher. The legacy Tk fallback is built by build_portable_tk.ps1.

    Output: desktop\release\OBS Overlay Import Utility Electron Portable.exe
#>

$ErrorActionPreference = "Stop"

function Assert-LastExit([string] $Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

function Install-ElectronDependencies([string] $DesktopPath) {
    $NodeModules = Join-Path $DesktopPath "node_modules"

    # node_modules is platform-specific and must not be reused from the Linux
    # Hermes workspace. Remove it before npm ci creates the Windows dependency
    # tree, instead of asking npm to delete a mixed-platform .bin directory.
    if (Test-Path -LiteralPath $NodeModules) {
        Write-Host "Removing existing Electron dependencies before the Windows install..."
        try {
            Remove-Item -LiteralPath $NodeModules -Recurse -Force -ErrorAction Stop
        }
        catch {
            throw "Could not remove $NodeModules. Close any Node/Electron processes using this workspace, then run the script again. $($_.Exception.Message)"
        }
    }

    Write-Host "Installing Electron dependencies..."
    & npm ci
    Assert-LastExit "Installing Electron dependencies"
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Desktop = Join-Path $Root "desktop"

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -m pip install -e "$Root[build]"
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m pip install -e "$Root[build]"
}
else {
    throw "Python 3.10 or newer was not found."
}
Assert-LastExit "Installing Python build dependencies"

Push-Location $Desktop
try {
    Install-ElectronDependencies $Desktop
    & npm run package
    Assert-LastExit "Electron portable application build"
}
finally {
    Pop-Location
}

$PortableApp = Join-Path $Desktop "release\OBS Overlay Import Utility Electron Portable.exe"
if (-not (Test-Path $PortableApp)) {
    throw "Electron portable executable was not created at $PortableApp."
}

Write-Host "Electron portable app created at:"
Write-Host $PortableApp
