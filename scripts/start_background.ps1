# バックグラウンドモードでアプリケーションを起動（PowerShell版）

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "ippi-down バックグラウンド起動スクリプト" -ForegroundColor Cyan
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

# バックグラウンドモードで起動
Write-Host ""
Write-Host "バックグラウンドモードでアプリケーションを起動しています..." -ForegroundColor Yellow
Write-Host ""

$env:PPI_BACKGROUND_MODE = "true"
python src\main.py --background

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "エラー: アプリケーションの起動に失敗しました" -ForegroundColor Red
    Read-Host "Enterキーを押して終了"
    exit 1
}

Write-Host ""
Write-Host "アプリケーションがバックグラウンドで実行されています" -ForegroundColor Green
Write-Host ""

