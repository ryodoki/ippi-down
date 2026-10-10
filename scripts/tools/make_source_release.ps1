# Create a clean source archive for development and audit.
param(
    [string]$OutputDir = "release",
    [string]$OutputName = "ippi-down-source.zip"
)

$ErrorActionPreference = "Stop"
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ResolvedOutputDir = if ([IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir
} else {
    Join-Path $ProjectRoot $OutputDir
}
$OutputPath = Join-Path $ResolvedOutputDir $OutputName
$TempDir = Join-Path ([IO.Path]::GetTempPath()) ("ippi-down-source-" + [guid]::NewGuid())
$PackageRoot = Join-Path $TempDir "ippi-down-source"

$ExcludedTopLevel = @(
    ".git", ".venv", "venv", "build", "dist", "downloads", "logs",
    "release", "test_downloads", "artifacts", "debug", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", ".tox", ".hypothesis", ".agents",
    ".codex", ".idea", ".vscode", "htmlcov"
)
$ExcludedNames = @(
    "config.yaml", ".coverage", ".env", ".env.local",
    "install-id", "install-location.json", "installation-relocation-journal.json",
    "schedule-instance-id",
    "schedule-registration.json",
    "self-check-result.txt",
    "Thumbs.db", "desktop.ini"
)
$ExcludedExtensions = @(
    ".pyc", ".pyo", ".log", ".zip", ".exe", ".part",
    ".pem", ".pfx", ".p12", ".key",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".rtf"
)

New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null
New-Item -ItemType Directory -Path $ResolvedOutputDir -Force | Out-Null

try {
    Get-ChildItem -LiteralPath $ProjectRoot -Recurse -Force -File | ForEach-Object {
        $RelativePath = $_.FullName.Substring($ProjectRoot.Length).TrimStart("\")
        $Segments = $RelativePath -split "[\\/]"
        $IsGeneratedDebugHtml = (
            $_.Name -eq "test_detail_page.html" -and
            $RelativePath -notlike "tests\fixtures\*"
        )
        $IsSecretLikeName = (
            $_.Name -match '(?i)^\.env(?:\.(?!example$|sample$|template$).+)?$' -or
            $_.Name -match '(?i)^(?:credentials?|secrets?|tokens?)\.(?:json|ya?ml|toml|ini|cfg|txt)$' -or
            $_.Name -match '(?i)^id_(?:rsa|dsa|ecdsa|ed25519)$'
        )
        $IsExcluded = (
            $ExcludedTopLevel -contains $Segments[0] -or
            $Segments -contains "__pycache__" -or
            $Segments -contains "schedule-profiles" -or
            $ExcludedNames -contains $_.Name -or
            $ExcludedExtensions -contains $_.Extension.ToLowerInvariant() -or
            $IsGeneratedDebugHtml -or
            $IsSecretLikeName
        )
        if (-not $IsExcluded) {
            $Destination = Join-Path $PackageRoot $RelativePath
            $DestinationDir = Split-Path -Parent $Destination
            New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $Destination -Force
        }
    }

    Compress-Archive -Path $PackageRoot -DestinationPath $OutputPath -Force
    $Hash = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash
    Write-Host "Created source release: $OutputPath" -ForegroundColor Green
    Write-Host "SHA-256: $Hash"
}
finally {
    if (Test-Path -LiteralPath $TempDir) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force
    }
}
