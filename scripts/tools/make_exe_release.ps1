# Create the end-user executable archive.
param(
    [string]$OutputDir = "release",
    [string]$OutputName = "ippi-down-windows-x64.zip"
)

$ErrorActionPreference = "Stop"
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ExePath = Join-Path $ProjectRoot "dist\ippi-down.exe"
if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw "Executable not found: $ExePath. Run scripts/build/build_exe.ps1 first."
}
$DownloadFolderSpecPath = Join-Path $ProjectRoot "docs\download_folder_spec.md"
if (-not (Test-Path -LiteralPath $DownloadFolderSpecPath -PathType Leaf)) {
    throw "Download folder specification not found: $DownloadFolderSpecPath"
}
$MemoryResourceSpecPath = Join-Path $ProjectRoot "docs\memory_resource_management.md"
if (-not (Test-Path -LiteralPath $MemoryResourceSpecPath -PathType Leaf)) {
    throw "Memory resource specification not found: $MemoryResourceSpecPath"
}
$NetworkSecuritySpecPath = Join-Path $ProjectRoot "docs\network_security.md"
if (-not (Test-Path -LiteralPath $NetworkSecuritySpecPath -PathType Leaf)) {
    throw "Network security specification not found: $NetworkSecuritySpecPath"
}
$PdfReliabilitySpecPath = Join-Path $ProjectRoot "docs\pdf_conversion_reliability.md"
if (-not (Test-Path -LiteralPath $PdfReliabilitySpecPath -PathType Leaf)) {
    throw "PDF conversion specification not found: $PdfReliabilitySpecPath"
}
$ThirdPartyNoticesPath = Join-Path $ProjectRoot "THIRD_PARTY_NOTICES.txt"
$FontLicensePath = Join-Path $ProjectRoot "src\resources\fonts\OFL-1.1.txt"
foreach ($RequiredPath in @($ThirdPartyNoticesPath, $FontLicensePath)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Third-party notice not found: $RequiredPath"
    }
}

$ResolvedOutputDir = if ([IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir
} else {
    Join-Path $ProjectRoot $OutputDir
}
$OutputPath = Join-Path $ResolvedOutputDir $OutputName
$TempDir = Join-Path ([IO.Path]::GetTempPath()) ("ippi-down-exe-" + [guid]::NewGuid())
$PackageRoot = Join-Path $TempDir "ippi-down"

New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PackageRoot "config") -Force | Out-Null
New-Item -ItemType Directory -Path $ResolvedOutputDir -Force | Out-Null

try {
    Copy-Item -LiteralPath $ExePath -Destination (Join-Path $PackageRoot "ippi-down.exe")
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "config\config.example.yaml") `
        -Destination (Join-Path $PackageRoot "config\config.example.yaml")
    # Package a dedicated end-user README with no repository-relative links.
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\README_EXE.md") `
        -Destination (Join-Path $PackageRoot "README.md")
    # Keep the canonical source document byte-for-byte identical in the
    # end-user package so README links remain package-local and auditable.
    Copy-Item -LiteralPath $DownloadFolderSpecPath `
        -Destination (Join-Path $PackageRoot "download_folder_spec.md")
    Copy-Item -LiteralPath $MemoryResourceSpecPath `
        -Destination (Join-Path $PackageRoot "memory_resource_management.md")
    Copy-Item -LiteralPath $NetworkSecuritySpecPath `
        -Destination (Join-Path $PackageRoot "network_security.md")
    Copy-Item -LiteralPath $PdfReliabilitySpecPath `
        -Destination (Join-Path $PackageRoot "pdf_conversion_reliability.md")
    Copy-Item -LiteralPath $ThirdPartyNoticesPath `
        -Destination (Join-Path $PackageRoot "THIRD_PARTY_NOTICES.txt")
    Copy-Item -LiteralPath $FontLicensePath `
        -Destination (Join-Path $PackageRoot "OFL-1.1.txt")

    $ExeHash = (Get-FileHash -LiteralPath (Join-Path $PackageRoot "ippi-down.exe") -Algorithm SHA256).Hash
    Set-Content -LiteralPath (Join-Path $PackageRoot "SHA256SUMS.txt") `
        -Value "$ExeHash  ippi-down.exe" -Encoding ASCII

    Compress-Archive -Path $PackageRoot -DestinationPath $OutputPath -Force
    $ZipHash = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash
    Write-Host "Created executable release: $OutputPath" -ForegroundColor Green
    Write-Host "SHA-256: $ZipHash"
}
finally {
    if (Test-Path -LiteralPath $TempDir) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force
    }
}
