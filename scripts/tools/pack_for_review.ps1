# レビュー/配布用ZIP作成（一本化スクリプト）
# config は config.example.yaml 等テンプレのみ同梱。config.yaml は同梱しない。
# 実行: プロジェクトルートで .\scripts\tools\pack_for_review.ps1 または scripts/tools から呼び出し

param(
    [string]$ProjectRoot = $null,
    [string]$OutDirName = "_review_pack",
    [string]$ZipName = "",
    [string[]]$ExtraIncludeDirs = @(),
    [string[]]$ExtraExcludeDirNames = @(),
    [string[]]$ExtraExcludeFilePatterns = @(),
    [string]$IncludeLogFile = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
}
Set-Location $ProjectRoot

function Write-Step($msg) { Write-Host "==> $msg" }
function Write-Warn($msg) { Write-Host "!!  $msg" -ForegroundColor Yellow }
function Write-Info($msg) { Write-Host "    $msg" }

# 含めるディレクトリ（config は後でテンプレのみ別処理）
$IncludeDirs = @("src", "tests", "docs", "scripts", "assets", "resources", "templates") + $ExtraIncludeDirs
$IncludeFiles = @(
    "README.md", "README.txt", "pyproject.toml", "poetry.lock", "uv.lock",
    "requirements.txt", "requirements-dev.txt", "requirements.lock",
    "pytest.ini", "tox.ini", ".coveragerc", ".gitignore", "LICENSE"
)
$ExcludeDirNames = @(
    ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".idea", ".vscode", "node_modules", "dist", "build", ".git", "logs", "downloads", "artifacts", "release"
) + $ExtraExcludeDirNames
$ExcludeFilePatterns = @(
    "*.pyc", "*.pyo", "*.log", "*.pfx", "*.pem", "*.key", ".env", ".env.*",
    "*secret*", "*token*", "*credential*", "*password*", "config.yaml"
) + $ExtraExcludeFilePatterns

$IncludeDirs = $IncludeDirs | Where-Object { $_ -and $_.Trim() -ne "" } | Select-Object -Unique
$ExcludeDirNames = $ExcludeDirNames | Where-Object { $_ -and $_.Trim() -ne "" } | Select-Object -Unique
$ExcludeFilePatterns = $ExcludeFilePatterns | Where-Object { $_ -and $_.Trim() -ne "" } | Select-Object -Unique

$OutDir = Join-Path $ProjectRoot $OutDirName
if (Test-Path $OutDir) {
    Write-Step "既存の出力フォルダを削除: $OutDir"
    Remove-Item $OutDir -Recurse -Force
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$ManifestPath = Join-Path $OutDir "MANIFEST.txt"
Set-Content -LiteralPath $ManifestPath -Value ""

function Add-Manifest($line) { Add-Content -LiteralPath $ManifestPath -Value $line }

Add-Manifest "Pack Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Add-Manifest "ProjectRoot: $ProjectRoot"
Add-Manifest ""

function Test-ExcludedFile([string]$fileName) {
    foreach ($pat in $ExcludeFilePatterns) {
        if ($fileName -like $pat) { return $true }
    }
    return $false
}

function Copy-DirFiltered($srcDir, $dstDir) {
    New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
    $items = Get-ChildItem -LiteralPath $srcDir -Force -ErrorAction SilentlyContinue
    foreach ($item in $items) {
        if ($item.PSIsContainer) {
            if ($ExcludeDirNames -contains $item.Name) { continue }
            $nextDst = Join-Path $dstDir $item.Name
            Copy-DirFiltered -srcDir $item.FullName -dstDir $nextDst
        } else {
            if (Test-ExcludedFile $item.Name) { continue }
            Copy-Item -LiteralPath $item.FullName -Destination $dstDir -Force
        }
    }
}

Write-Step "フォルダのコピー開始"
foreach ($d in $IncludeDirs) {
    $src = Join-Path $ProjectRoot $d
    if (Test-Path $src) {
        $dst = Join-Path $OutDir $d
        Write-Info "コピー: $d"
        Copy-DirFiltered -srcDir $src -dstDir $dst
    }
}

# config/ はテンプレのみ（config.example.yaml 等）。config.yaml は含めない
$configSrc = Join-Path $ProjectRoot "config"
if (Test-Path $configSrc) {
    $configDst = Join-Path $OutDir "config"
    New-Item -ItemType Directory -Path $configDst -Force | Out-Null
    $templatePatterns = @("*.example.*", "*.sample.*", "*.template.*", "*example*", "*sample*", "*template*")
    $templates = @()
    foreach ($pat in $templatePatterns) {
        $templates += Get-ChildItem -LiteralPath $configSrc -File -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -like $pat }
    }
    $templates = @($templates | Select-Object -Unique -Property FullName | ForEach-Object { $_ })
    if ($templates.Count -gt 0) {
        Write-Step "config/ はテンプレのみ同梱（config.yaml は含めません）"
        foreach ($t in $templates) {
            $rel = $t.FullName.Substring($configSrc.Length).TrimStart("\")
            $dstPath = Join-Path $configDst $rel
            $dstParent = Split-Path $dstPath -Parent
            New-Item -ItemType Directory -Path $dstParent -Force | Out-Null
            Copy-Item -LiteralPath $t.FullName -Destination $dstPath -Force
        }
    } else {
        Write-Warn "config/ にテンプレートファイルが見つかりません。config.example.yaml を配置してください。"
    }
}

Write-Step "単体ファイルのコピー"
foreach ($f in $IncludeFiles) {
    $src = Join-Path $ProjectRoot $f
    if (Test-Path $src) {
        Copy-Item -LiteralPath $src -Destination $OutDir -Force
        Write-Info "コピー: $f"
    }
}

# config がルートに config.example.yaml の場合
$configExample = Join-Path $ProjectRoot "config\config.example.yaml"
if (Test-Path $configExample) {
    $configDst = Join-Path $OutDir "config"
    if (-not (Test-Path $configDst)) { New-Item -ItemType Directory -Path $configDst -Force | Out-Null }
    Copy-Item -LiteralPath $configExample -Destination $configDst -Force
    Write-Info "コピー: config/config.example.yaml"
}

if (-not [string]::IsNullOrWhiteSpace($IncludeLogFile)) {
    $logSrc = Join-Path $ProjectRoot $IncludeLogFile
    if (Test-Path $logSrc) {
        $logDstDir = Join-Path $OutDir "logs"
        New-Item -ItemType Directory -Path $logDstDir -Force | Out-Null
        Copy-Item -LiteralPath $logSrc -Destination $logDstDir -Force
        Write-Step "ログ1本のみ同梱: $IncludeLogFile"
    }
}

if ([string]::IsNullOrWhiteSpace($ZipName)) {
    $projName = Split-Path $ProjectRoot -Leaf
    $ZipName = "${projName}_review.zip"
}
$ZipPath = Join-Path $ProjectRoot $ZipName
if (Test-Path $ZipPath) {
    Write-Step "既存ZIPを削除: $ZipPath"
    Remove-Item $ZipPath -Force
}
Write-Step "ZIP作成: $ZipName"
Compress-Archive -Path (Join-Path $OutDir "*") -DestinationPath $ZipPath -Force

Write-Step "完了"
Write-Host ""
Write-Host "出力フォルダ: $OutDir"
Write-Host "ZIP:          $ZipPath"
Write-Host ""
Write-Host "除外確認: .venv, build, dist, logs, config/config.yaml は含まれていません。" -ForegroundColor Yellow
