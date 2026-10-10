# 依存関係を再導入してから安全なPyInstallerビルドを実行（PowerShell版）
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BuildScript = Join-Path $PSScriptRoot "build_exe.ps1"

Push-Location $ProjectRoot
try {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "ippi-down 実行ファイル再ビルドスクリプト" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "仮想環境が見つかりません: $PythonExe`n先に scripts\setup.ps1 -WithBuild を実行してください。"
    }

    & $PythonExe -c "import struct, sys, tkinter; tcl = tkinter.Tcl(); valid = sys.version_info[:2] == (3, 11) and struct.calcsize('P') * 8 == 64 and all('conda' not in str(value).lower() for value in (sys.executable, sys.base_prefix)); raise SystemExit(0 if valid and tcl.eval('info patchlevel') else 1)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "プロジェクトの.venvが壊れているか、Tk対応Python 3.11 x64以外またはCondaを参照しています。`nscripts\setup.ps1 -WithBuild を実行して再作成してください。"
    }

    Write-Host ""
    Write-Host "依存関係を再インストールしています..." -ForegroundColor Yellow
    & $PythonExe -m pip install -c requirements\constraints.txt -r requirements\build.txt
    if ($LASTEXITCODE -ne 0) {
        throw "依存関係のインストールに失敗しました。既存のexeと利用者データは変更していません。"
    }
}
finally {
    Pop-Location
}

# distを削除しない安全なビルド処理は1つの正本へ集約する。
& $BuildScript
