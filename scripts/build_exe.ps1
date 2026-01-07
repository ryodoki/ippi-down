# PyInstallerを使用して実行ファイルをビルド（PowerShell版）

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "ippi-down 実行ファイルビルドスクリプト" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 仮想環境の有効化
if (Test-Path ".venv\Scripts\Activate.ps1") {
    Write-Host "仮想環境を有効化しています..." -ForegroundColor Yellow
    & .venv\Scripts\Activate.ps1
} elseif (Test-Path ".venv\Scripts\activate.bat") {
    Write-Host "仮想環境を有効化しています..." -ForegroundColor Yellow
    & .venv\Scripts\activate.bat
} else {
    Write-Host "警告: 仮想環境が見つかりません" -ForegroundColor Red
    Write-Host "仮想環境を作成してください: python -m venv .venv" -ForegroundColor Yellow
    Read-Host "Enterキーを押して終了"
    exit 1
}

# PyInstallerのインストール確認
try {
    python -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller not found"
    }
} catch {
    Write-Host "PyInstallerをインストールしています..." -ForegroundColor Yellow
    pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        Write-Host "エラー: PyInstallerのインストールに失敗しました" -ForegroundColor Red
        Read-Host "Enterキーを押して終了"
        exit 1
    }
}

# ビルドディレクトリのクリーンアップ
if (Test-Path "build") {
    Write-Host "既存のビルドディレクトリを削除しています..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "build"
}
if (Test-Path "dist") {
    Write-Host "既存のdistディレクトリを削除しています..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "dist"
}

# PyInstallerで実行ファイルをビルド
Write-Host ""
Write-Host "実行ファイルをビルドしています..." -ForegroundColor Yellow
Write-Host "これには数分かかる場合があります..." -ForegroundColor Yellow
Write-Host ""

pyinstaller build.spec

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "エラー: ビルドに失敗しました" -ForegroundColor Red
    Read-Host "Enterキーを押して終了"
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "ビルドが完了しました！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "実行ファイルの場所: dist\ippi-down.exe" -ForegroundColor Cyan
Write-Host ""

Read-Host "Enterキーを押して終了"

