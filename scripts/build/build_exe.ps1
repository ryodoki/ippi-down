# PyInstallerを使用して実行ファイルを安全にビルド（PowerShell版）
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BuildDir = Join-Path $ProjectRoot "build"
$WorkDir = Join-Path $BuildDir "pyinstaller-work"
$StagedDist = Join-Path $BuildDir "staged-dist"
$StagedExe = Join-Path $StagedDist "ippi-down.exe"
$DistDir = Join-Path $ProjectRoot "dist"
$TargetExe = Join-Path $DistDir "ippi-down.exe"

Push-Location $ProjectRoot
try {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "ippi-down 実行ファイルビルドスクリプト" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "仮想環境が見つかりません: $PythonExe`n先に scripts\setup.ps1 -WithBuild を実行してください。"
    }

    & $PythonExe -c "import struct, sys, tkinter; tcl = tkinter.Tcl(); valid = sys.version_info[:2] == (3, 11) and struct.calcsize('P') * 8 == 64 and all('conda' not in str(value).lower() for value in (sys.executable, sys.base_prefix)); raise SystemExit(0 if valid and tcl.eval('info patchlevel') else 1)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "プロジェクトの.venvが壊れているか、Tk対応Python 3.11 x64以外またはCondaを参照しています。`nscripts\setup.ps1 -WithBuild を実行して再作成してください。"
    }

    & $PythonExe -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstallerがありません。requirements/build.txtをconstraints付きで導入してください。"
    }

    # buildは使い捨ての中間物だけを置く場所。distには設定、ログ、取得文書が
    # 置かれる場合があるため、ディレクトリ単位では絶対に削除しない。
    if (Test-Path -LiteralPath $BuildDir) {
        Write-Host "既存のビルドディレクトリを削除しています..." -ForegroundColor Yellow
        Remove-Item -LiteralPath $BuildDir -Recurse -Force
    }

    Write-Host ""
    Write-Host "一時出力へ実行ファイルをビルドしています..." -ForegroundColor Yellow
    Write-Host "これには数分かかる場合があります..." -ForegroundColor Yellow
    Write-Host ""

    & $PythonExe -m PyInstaller `
        --noconfirm `
        --workpath $WorkDir `
        --distpath $StagedDist `
        scripts\build\build.spec

    if ($LASTEXITCODE -ne 0) {
        throw "ビルドに失敗しました。既存のdist\ippi-down.exeと利用者データは変更していません。"
    }
    if (-not (Test-Path -LiteralPath $StagedExe -PathType Leaf)) {
        throw "一時出力にippi-down.exeがありません。既存のexeは変更していません。"
    }

    # PyInstallerが成功終了しても、空ファイルやexe以外を正式名へ置換しない。
    $ValidationCode = @'
from pathlib import Path
import sys

path = Path(sys.argv[1])
with path.open(mode=chr(114) + chr(98)) as stream:
    signature = stream.read(2)
raise SystemExit(0 if path.stat().st_size > 0 and signature == bytes((77, 90)) else 1)
'@
    & $PythonExe -c $ValidationCode $StagedExe
    if ($LASTEXITCODE -ne 0) {
        throw "生成されたippi-down.exeの検証に失敗しました。既存のexeは変更していません。"
    }

    if (-not (Test-Path -LiteralPath $DistDir -PathType Container)) {
        New-Item -ItemType Directory -Path $DistDir | Out-Null
    }

    # 同一ボリューム内のos.replaceでexeだけを原子的に置換する。実行中のexeが
    # Windowsによりロックされていれば失敗し、旧exeとdist内の利用者データは残る。
    & $PythonExe -c "import os, sys; os.replace(sys.argv[1], sys.argv[2])" $StagedExe $TargetExe
    if ($LASTEXITCODE -ne 0) {
        throw "dist\ippi-down.exeを置換できません。アプリを終了して再実行してください。旧exeと利用者データは保持されています。"
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "ビルドが完了しました！" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "実行ファイルの場所: dist\ippi-down.exe" -ForegroundColor Cyan
    Write-Host "dist内のconfig、downloads、logsなどは変更していません。" -ForegroundColor Cyan
    Write-Host ""
}
finally {
    Pop-Location
}
