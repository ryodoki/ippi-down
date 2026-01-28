param(
    # プロジェクトルート（デフォルトはカレント）
    [string]$ProjectRoot = (Get-Location).Path,

    # 出力フォルダ名
    [string]$OutDirName = "_review_pack",

    # ZIP名（空なら自動）
    [string]$ZipName = "",

    # 追加で含めたいフォルダ（任意、複数可）: -ExtraIncludeDirs "foo","bar"
    [string[]]$ExtraIncludeDirs = @(),

    # 追加で除外したいフォルダ名（任意、複数可）: -ExtraExcludeDirNames "data","output"
    [string[]]$ExtraExcludeDirNames = @(),

    # 追加で除外したいファイルパターン（任意、複数可）: -ExtraExcludeFilePatterns "*.xlsx","*.pdf"
    [string[]]$ExtraExcludeFilePatterns = @(),

    # 例: "logs\app.log" のように指定するとその1本だけ同梱（任意）
    [string]$IncludeLogFile = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "==> $msg" }
function Write-Warn($msg) { Write-Host "!!  $msg" -ForegroundColor Yellow }
function Write-Info($msg) { Write-Host "    $msg" }

# -----------------------------
# 1) ルール定義（基本値）
# -----------------------------
$IncludeDirs = @(
    "src",
    "tests",
    "docs",
    "scripts",
    "assets",
    "resources",
    "templates"
)

# configは特殊扱い（後でテンプレ優先処理する）
$IncludeConfigDir = $true

$IncludeFiles = @(
    "README.md",
    "README.txt",
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

# 生成物/機密系の除外パターン（ファイル名ベース）
$ExcludeFilePatterns = @(
    "*.pyc",
    "*.pyo",
    "*.log",         # ログは基本除外（必要なら1本だけ指定で入れる）
    "*.pfx",
    "*.pem",
    "*.key",
    ".env",
    ".env.*",
    "*secret*",
    "*token*",
    "*credential*",
    "*password*"
)

# 追加指定を反映
$IncludeDirs += $ExtraIncludeDirs
$ExcludeDirNames += $ExtraExcludeDirNames
$ExcludeFilePatterns += $ExtraExcludeFilePatterns

# 重複排除
$IncludeDirs = $IncludeDirs | Where-Object { $_ -and $_.Trim() -ne "" } | Select-Object -Unique
$ExcludeDirNames = $ExcludeDirNames | Where-Object { $_ -and $_.Trim() -ne "" } | Select-Object -Unique
$ExcludeFilePatterns = $ExcludeFilePatterns | Where-Object { $_ -and $_.Trim() -ne "" } | Select-Object -Unique

# -----------------------------
# 2) 出力先準備
# -----------------------------
$OutDir = Join-Path $ProjectRoot $OutDirName
if (Test-Path $OutDir) {
    Write-Step "既存の出力フォルダを削除: $OutDir"
    Remove-Item $OutDir -Recurse -Force
}
New-Item -ItemType Directory -Path $OutDir | Out-Null

$ManifestPath = Join-Path $OutDir "MANIFEST.txt"
New-Item -ItemType File -Path $ManifestPath -Force | Out-Null

function Add-Manifest($line) {
    Add-Content -LiteralPath $ManifestPath -Value $line
}

Add-Manifest "Pack Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Add-Manifest "ProjectRoot: $ProjectRoot"
Add-Manifest "OutDir: $OutDir"
Add-Manifest ""
Add-Manifest "=== Include Dirs ==="
$IncludeDirs | ForEach-Object { Add-Manifest $_ }
Add-Manifest ""
Add-Manifest "=== Include Files ==="
$IncludeFiles | ForEach-Object { Add-Manifest $_ }
Add-Manifest ""
Add-Manifest "=== Exclude Dir Names ==="
$ExcludeDirNames | ForEach-Object { Add-Manifest $_ }
Add-Manifest ""
Add-Manifest "=== Exclude File Patterns ==="
$ExcludeFilePatterns | ForEach-Object { Add-Manifest $_ }
Add-Manifest ""
Add-Manifest "=== Actions ==="

# -----------------------------
# 3) コピー関数（除外しながら）
# -----------------------------
function Test-ExcludedFile([string]$fileName) {
    foreach ($pat in $ExcludeFilePatterns) {
        if ($fileName -like $pat) { return $true }
    }
    return $false
}

function Copy-DirFiltered($srcDir, $dstDir) {
    New-Item -ItemType Directory -Path $dstDir -Force | Out-Null

    $items = Get-ChildItem -LiteralPath $srcDir -Force
    foreach ($item in $items) {
        if ($item.PSIsContainer) {
            if ($ExcludeDirNames -contains $item.Name) {
                Add-Manifest "SKIP_DIR  $($item.FullName)"
                continue
            }
            $nextDst = Join-Path $dstDir $item.Name
            Copy-DirFiltered -srcDir $item.FullName -dstDir $nextDst
        } else {
            if (Test-ExcludedFile $item.Name) {
                Add-Manifest "SKIP_FILE $($item.FullName)"
                continue
            }
            Copy-Item -LiteralPath $item.FullName -Destination $dstDir -Force
            Add-Manifest "COPY_FILE $($item.FullName)"
        }
    }
}

# -----------------------------
# 4) 通常フォルダコピー
# -----------------------------
Write-Step "フォルダのコピー開始"
foreach ($d in $IncludeDirs) {
    $src = Join-Path $ProjectRoot $d
    if (Test-Path $src) {
        $dst = Join-Path $OutDir $d
        Write-Info "コピー: $d"
        Add-Manifest "COPY_DIR  $src"
        Copy-DirFiltered -srcDir $src -dstDir $dst
    }
}

# -----------------------------
# 5) config/ の特殊処理（テンプレ優先）
# -----------------------------
if ($IncludeConfigDir) {
    $configSrc = Join-Path $ProjectRoot "config"
    if (Test-Path $configSrc) {
        $configDst = Join-Path $OutDir "config"
        New-Item -ItemType Directory -Path $configDst -Force | Out-Null

        # まずテンプレだけ集める（example / sample / template を優先）
        $templates = @()
        foreach ($pat in $templatePatterns) {
            $templates += Get-ChildItem -LiteralPath $configSrc -File -Recurse -Force -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -like $pat }
        }

        # ★ここが重要：Unique後も“配列”に固定
        $templates = @($templates | Select-Object -Unique)

        if ($templates.Count -gt 0) {
            Write-Step "config/ はテンプレのみ同梱（実設定は入れへん）"
            Add-Manifest "CONFIG_MODE TEMPLATE_ONLY"
            foreach ($t in $templates) {
                # 相対パスを保ってコピー
                $rel = $t.FullName.Substring($configSrc.Length).TrimStart("\")
                $dstPath = Join-Path $configDst $rel
                $dstParent = Split-Path $dstPath -Parent
                New-Item -ItemType Directory -Path $dstParent -Force | Out-Null
                Copy-Item -LiteralPath $t.FullName -Destination $dstPath -Force
                Add-Manifest "COPY_CONFIG_TEMPLATE $($t.FullName)"
            }
        } else {
            # テンプレが無い場合は「configは同梱しない」か「安全そうなものだけ」か迷うが、
            # 事故防止のため同梱せず警告にする（勝手に入れて漏らす方がヤバい）
            Write-Warn "config/ にテンプレっぽいファイルが見つからん。実設定を入れると漏えいリスク高いので config/ は同梱せず警告にした。"
            Add-Manifest "CONFIG_MODE SKIP_NO_TEMPLATE"
        }
    }
}

# -----------------------------
# 6) 単体ファイルコピー
# -----------------------------
Write-Step "単体ファイルのコピー開始"
foreach ($f in $IncludeFiles) {
    $src = Join-Path $ProjectRoot $f
    if (Test-Path $src) {
        Copy-Item -LiteralPath $src -Destination $OutDir -Force
        Write-Info "コピー: $f"
        Add-Manifest "COPY_FILE $src"
    }
}

# -----------------------------
# 7) 指定ログファイルを1本だけ同梱（任意）
# -----------------------------
if (-not [string]::IsNullOrWhiteSpace($IncludeLogFile)) {
    $logSrc = Join-Path $ProjectRoot $IncludeLogFile
    if (Test-Path $logSrc) {
        $logDstDir = Join-Path $OutDir "logs"
        New-Item -ItemType Directory -Path $logDstDir -Force | Out-Null
        Copy-Item -LiteralPath $logSrc -Destination $logDstDir -Force
        Write-Step "ログ1本だけ同梱: $IncludeLogFile"
        Add-Manifest "COPY_LOG_SINGLE $logSrc"
    } else {
        Write-Warn "指定されたログが見つからん: $IncludeLogFile"
        Add-Manifest "LOG_MISSING $logSrc"
    }
}

# -----------------------------
# 8) 軽い秘密情報スキャン（警告のみ）
# -----------------------------
Write-Step "秘密情報っぽい文字列を軽くスキャン（警告のみ）"
$SuspiciousPatterns = @(
    "AKIA[0-9A-Z]{16}",        # AWS Access Keyっぽい
    "-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----",
    "password\s*[:=]",
    "token\s*[:=]",
    "secret\s*[:=]",
    "api[_-]?key\s*[:=]"
)

$scanTargets = Get-ChildItem -LiteralPath $OutDir -File -Recurse -Force |
    Where-Object { $_.Extension -in @(".py",".txt",".md",".yaml",".yml",".toml",".ini",".json",".cfg",".env") }

$hits = 0
foreach ($file in $scanTargets) {
    try {
        $content = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction Stop
        foreach ($pat in $SuspiciousPatterns) {
            if ($content -match $pat) {
                $hits++
                Write-Warn "疑わしい一致: $($file.FullName)  /  pattern=$pat"
                Add-Manifest "SUSPECT_HIT $($file.FullName) pattern=$pat"
                break
            }
        }
    } catch {
        # バイナリ等は無視
    }
}
if ($hits -eq 0) {
    Write-Info "目立つ一致は見つからんかった（だから安全、とは限らん）"
    Add-Manifest "SUSPECT_HIT none"
}

# -----------------------------
# 9) ZIP化
# -----------------------------
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
Write-Host "出力フォルダ: $OutDir"
Write-Host "MANIFEST:   $ManifestPath"
Write-Host "ZIP:        $ZipPath"
