param(
    [string]$ProjectRoot = (Get-Location).Path,
    [string]$OutDirName = "_review_pack",
    [string]$ZipName = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host "==> $msg"
}

# 1) 出力先
$OutDir = Join-Path $ProjectRoot $OutDirName
if (Test-Path $OutDir) {
    Write-Step "既存の出力フォルダを削除: $OutDir"
    Remove-Item $OutDir -Recurse -Force
}
New-Item -ItemType Directory -Path $OutDir | Out-Null

# 2) 含める対象（必要に応じて調整）
# 注意: config ディレクトリは含めない（config.yaml が混入するリスクがあるため）
$IncludeDirs = @(
    "src",
    "tests",
    "docs",
    "scripts",
    "assets",
    "resources",
    "templates"
)

$IncludeFiles = @(
    "README.md",
    "README.txt",
    "config.example.yaml",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements.lock",
    "pytest.ini",
    "tox.ini",
    ".coveragerc",
    ".gitignore",
    "LICENSE"
)

# 3) 除外したいフォルダ名（どこにあっても除外）
$ExcludeDirNames = @(
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
    ".vscode",
    "node_modules",
    "dist",
    "build",
    ".git"
)

# 4) 除外したいファイルパターン（秘密情報・生成物）
$ExcludeFilePatterns = @(
    "*.pyc",
    "*.pyo",
    "*.log",
    "config.yaml",  # 実設定ファイルを除外
    "*.pfx",
    "*.pem",
    "*.key",
    ".env",
    ".env.*",
    "*secret*",
    "*token*",
    "*credential*"
)

# 5) ディレクトリコピー（除外しながら）
function Copy-DirFiltered($srcDir, $dstDir) {
    New-Item -ItemType Directory -Path $dstDir -Force | Out-Null

    $items = Get-ChildItem -LiteralPath $srcDir -Force
    foreach ($item in $items) {

        if ($item.PSIsContainer) {
            if ($ExcludeDirNames -contains $item.Name) {
                continue
            }
            $nextDst = Join-Path $dstDir $item.Name
            Copy-DirFiltered -srcDir $item.FullName -dstDir $nextDst
        } else {
            $excluded = $false
            foreach ($pat in $ExcludeFilePatterns) {
                if ($item.Name -like $pat) { $excluded = $true; break }
            }
            if ($excluded) { continue }

            Copy-Item -LiteralPath $item.FullName -Destination $dstDir -Force
        }
    }
}

Write-Step "フォルダのコピー開始"
foreach ($d in $IncludeDirs) {
    $src = Join-Path $ProjectRoot $d
    if (Test-Path $src) {
        $dst = Join-Path $OutDir $d
        Write-Step "コピー: $d"
        Copy-DirFiltered -srcDir $src -dstDir $dst
    }
}

Write-Step "単体ファイルのコピー開始"
foreach ($f in $IncludeFiles) {
    $src = Join-Path $ProjectRoot $f
    if (Test-Path $src) {
        # config.yaml は除外（実設定ファイル）
        if ($f -eq "config.yaml") {
            Write-Step "スキップ（実設定ファイル）: $f"
            continue
        }
        Copy-Item -LiteralPath $src -Destination $OutDir -Force
        Write-Step "コピー: $f"
    }
}

# config.example.yaml のみ手動でコピー（テンプレート）
$configExample = Join-Path $ProjectRoot "config.example.yaml"
if (Test-Path $configExample) {
    Copy-Item -LiteralPath $configExample -Destination $OutDir -Force
    Write-Step "コピー: config.example.yaml（テンプレート）"
}

# 6) ZIP化
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

Write-Step "完了: $ZipPath"
Write-Host ""
Write-Host "出力フォルダ: $OutDir"
Write-Host "ZIP: $ZipPath"
