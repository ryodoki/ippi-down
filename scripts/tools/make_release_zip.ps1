# Compatibility wrapper for source and executable archives.
param(
    [ValidateSet("Source", "Exe")]
    [string]$PackageType = "Source",
    [string]$OutputDir = "release"
)

$ErrorActionPreference = "Stop"
$Script = if ($PackageType -eq "Exe") {
    Join-Path $PSScriptRoot "make_exe_release.ps1"
} else {
    Join-Path $PSScriptRoot "make_source_release.ps1"
}

& $Script -OutputDir $OutputDir
