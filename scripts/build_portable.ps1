<#
.SYNOPSIS
    Builds the primary Electron portable application.

.DESCRIPTION
    Compatibility entry point for existing invocations. By default it builds
    the primary Electron + React portable application. Pass -LegacyTk only to
    build the separately maintained legacy Tk fallback.
#>

[CmdletBinding()]
param(
    [switch] $LegacyTk
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

if ($LegacyTk) {
    Write-Host "Building the legacy Tk fallback."
    & (Join-Path $ScriptDir "build_portable_tk.ps1")
}
else {
    Write-Host "Building the primary Electron portable application."
    & (Join-Path $ScriptDir "build_portable_electron.ps1")
}
