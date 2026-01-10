# クリーンな配布用zipファイルを作成するスクリプト
# 除外対象: .git, .venv, __pycache__, *.pyc, .pytest_cache, build, dist, logs, downloads, config/config.yaml

param(
    [string]$OutputDir = "release",
    [string]$OutputName = "ippi-down-clean.zip"
)

$ErrorActionPreference = "Stop"

# スクリプトのディレクトリに移動
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "=== クリーンな配布用zipファイルを作成 ===" -ForegroundColor Cyan
Write-Host "プロジェクトルート: $ProjectRoot" -ForegroundColor Gray
Write-Host ""

# 出力ディレクトリを作成
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    Write-Host "出力ディレクトリを作成しました: $OutputDir" -ForegroundColor Green
}

$OutputPath = Join-Path $OutputDir $OutputName

# 既存のzipファイルを削除
if (Test-Path $OutputPath) {
    Remove-Item $OutputPath -Force
    Write-Host "既存のzipファイルを削除しました: $OutputPath" -ForegroundColor Yellow
}

# 除外対象のパターン
$ExcludePatterns = @(
    ".git",
    ".venv",
    "venv",
    "ENV",
    "env",
    "__pycache__",
    ".pytest_cache",
    "build",
    "dist",
    "logs",
    "downloads",
    ".tox",
    ".hypothesis",
    ".coverage",
    "htmlcov",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.egg-info",
    ".eggs",
    "*.spec",
    "*.exe",
    "*.dll",
    "*.dylib",
    "*.log",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ".vscode",
    ".idea",
    "*.swp",
    "*.swo",
    "*~",
    ".env",
    ".env.local",
    "config/config.yaml",
    "release"
)

Write-Host "除外対象:" -ForegroundColor Cyan
foreach ($pattern in $ExcludePatterns) {
    Write-Host "  - $pattern" -ForegroundColor Gray
}
Write-Host ""

# 一時ディレクトリを作成
$TempDir = Join-Path $env:TEMP "ippi-down-release-$(Get-Date -Format 'yyyyMMddHHmmss')"
if (Test-Path $TempDir) {
    Remove-Item $TempDir -Recurse -Force
}
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
Write-Host "一時ディレクトリを作成しました: $TempDir" -ForegroundColor Gray
Write-Host ""

try {
    # ファイルをコピー（除外対象をスキップ）
    $CopiedCount = 0
    $SkippedCount = 0
    
    Write-Host "ファイルをコピー中..." -ForegroundColor Cyan
    
    Get-ChildItem -Path . -Recurse -Force | Where-Object {
        $item = $_
        $relativePath = $item.FullName.Substring($ProjectRoot.Length + 1).Replace('\', '/')
        
        # 除外判定
        $shouldExclude = $false
        
        # .git/ディレクトリを明示的に除外
        if ($relativePath -like ".git*" -or $item.Name -eq ".git") {
            $shouldExclude = $true
        }
        
        # config/config.yamlを明示的に除外
        if ($relativePath -eq "config\config.yaml" -or $relativePath -eq "config/config.yaml") {
            $shouldExclude = $true
        }
        
        # 除外パターンに一致するかチェック
        foreach ($pattern in $ExcludePatterns) {
            # ワイルドカード対応
            if ($pattern -match '\*') {
                $basePattern = $pattern.Replace('*', '')
                if ($relativePath -like "*$basePattern*" -or $item.Name -like "*$basePattern*") {
                    $shouldExclude = $true
                    break
                }
            } else {
                # ディレクトリ名またはファイル名が一致
                if ($relativePath -like "*\$pattern*" -or $relativePath -like "*/$pattern*" -or $relativePath -eq $pattern -or $item.Name -eq $pattern) {
                    $shouldExclude = $true
                    break
                }
            }
        }
        
        # 隠しファイル・ディレクトリを除外（.git, .venvなど、ただし.gitignoreと.gitkeepは含める）
        if ($item.Name.StartsWith('.')) {
            if ($item.Name -eq '.gitignore' -or $item.Name -eq '.gitkeep') {
                # .gitignoreと.gitkeepは含める
                $shouldExclude = $false
            } elseif ($relativePath -notlike ".gitignore" -and $relativePath -notlike "*/.gitkeep") {
                # その他の隠しファイル・ディレクトリは除外
                $shouldExclude = $true
            }
        }
        
        # .gitignoreファイルは必ず含める
        if ($item.Name -eq ".gitignore") {
            $shouldExclude = $false
        }
        
        -not $shouldExclude
    } | ForEach-Object {
        $item = $_
        $relativePath = $item.FullName.Substring($ProjectRoot.Length + 1)
        $destPath = Join-Path $TempDir $relativePath
        $destDir = Split-Path $destPath -Parent
        
        try {
            if (-not (Test-Path $destDir)) {
                New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            }
            
            if (-not $item.PSIsContainer) {
                Copy-Item $item.FullName -Destination $destPath -Force | Out-Null
                $script:CopiedCount++
            }
        } catch {
            Write-Warning "コピーに失敗: $relativePath - $($_.Exception.Message)"
            $script:SkippedCount++
        }
    }
    
    Write-Host ""
    Write-Host "コピー完了: $CopiedCount ファイル" -ForegroundColor Green
    if ($SkippedCount -gt 0) {
        Write-Host "スキップ: $SkippedCount ファイル" -ForegroundColor Yellow
    }
    Write-Host ""
    
    # zipファイルを作成
    Write-Host "zipファイルを作成中..." -ForegroundColor Cyan
    
    # 7-Zipが利用可能かチェック
    $use7Zip = $false
    $7ZipPath = "C:\Program Files\7-Zip\7z.exe"
    if (Test-Path $7ZipPath) {
        $use7Zip = $true
        Write-Host "7-Zipを使用します" -ForegroundColor Gray
        
        # 7-Zipでzip作成（除外リストを使用）
        Push-Location $TempDir
        & $7ZipPath a -tzip $OutputPath * | Out-Null
        Pop-Location
        
        # 出力パスを絶対パスに変換
        $OutputPath = (Resolve-Path $OutputPath).Path
    } else {
        Write-Host "PowerShellのCompress-Archiveを使用します" -ForegroundColor Gray
        
        # Compress-Archiveを使用
        $zipTemp = Join-Path $env:TEMP "ippi-down-zip-$(Get-Date -Format 'yyyyMMddHHmmss')"
        if (Test-Path $zipTemp) {
            Remove-Item $zipTemp -Recurse -Force
        }
        New-Item -ItemType Directory -Path $zipTemp -Force | Out-Null
        
        # プロジェクト名のディレクトリを作成
        $ProjectNameDir = Join-Path $zipTemp "ippi-down"
        New-Item -ItemType Directory -Path $ProjectNameDir -Force | Out-Null
        
        # ファイルをコピー
        Get-ChildItem -Path $TempDir -Recurse | Copy-Item -Destination {
            $_.FullName.Replace($TempDir, $ProjectNameDir)
        } -Recurse -Force
        
        # zip作成
        Compress-Archive -Path "$ProjectNameDir\*" -DestinationPath $OutputPath -Force
        
        # 一時ディレクトリを削除
        Remove-Item $zipTemp -Recurse -Force
        
        $OutputPath = (Resolve-Path $OutputPath).Path
    }
    
    Write-Host ""
    Write-Host "=== zipファイル作成完了 ===" -ForegroundColor Green
    Write-Host "出力先: $OutputPath" -ForegroundColor Cyan
    
    # zipファイルサイズを表示
    $zipSize = (Get-Item $OutputPath).Length
    $zipSizeMB = [math]::Round($zipSize / 1MB, 2)
    Write-Host "ファイルサイズ: $zipSizeMB MB ($zipSize bytes)" -ForegroundColor Gray
    Write-Host ""
    
    # 含まれているファイル数を確認
    if ($use7Zip) {
        $zipContents = & $7ZipPath l $OutputPath | Select-String -Pattern "^\d" | Measure-Object
        Write-Host "含まれているファイル数: $($zipContents.Count)" -ForegroundColor Gray
    }
    
    Write-Host ""
    Write-Host "除外確認: 以下のファイル・ディレクトリが含まれていないことを確認してください" -ForegroundColor Yellow
    Write-Host "  - .git/" -ForegroundColor Gray
    Write-Host "  - .venv/" -ForegroundColor Gray
    Write-Host "  - __pycache__/" -ForegroundColor Gray
    Write-Host "  - build/, dist/" -ForegroundColor Gray
    Write-Host "  - logs/, downloads/" -ForegroundColor Gray
    Write-Host "  - config/config.yaml" -ForegroundColor Gray
    
} finally {
    # 一時ディレクトリを削除
    if (Test-Path $TempDir) {
        Remove-Item $TempDir -Recurse -Force
        Write-Host ""
        Write-Host "一時ディレクトリを削除しました" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "完了！" -ForegroundColor Green
