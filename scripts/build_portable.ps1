<#
.SYNOPSIS
    Builds the legacy Tk fallback Windows executable.

.DESCRIPTION
    This is the legacy Tk fallback build script. It has been renamed to
    build_portable_tk.ps1 for clarity. This file remains as a backward-
    compatible redirect.

    For the primary Electron + React portable app, use:
        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_portable_electron.ps1

    Output: dist\OBS Overlay Import Utility.exe (Tk fallback)
#>

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$TkScript = Join-Path $ScriptDir "build_portable_tk.ps1"

Write-Host "This is the legacy Tk fallback build script."
Write-Host "Redirecting to build_portable_tk.ps1..."
Write-Host ""

& $TkScript
