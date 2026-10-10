# バックグラウンドモードでアプリケーションを起動（PowerShell版）
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "仮想環境が見つかりません: $PythonExe`n先に scripts\setup.ps1 を実行してください。"
}

& $PythonExe -c "import struct, sys; valid = sys.version_info[:2] == (3, 11) and struct.calcsize('P') * 8 == 64 and all('conda' not in str(value).lower() for value in (sys.executable, sys.base_prefix)); raise SystemExit(0 if valid else 1)" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "プロジェクトの.venvが壊れているか、Python 3.11 x64以外またはCondaを参照しています。`nscripts\setup.ps1 を実行して再作成してください。"
}

Push-Location $ProjectRoot
try {
    $env:PPI_BACKGROUND_MODE = "true"
    & $PythonExe (Join-Path $ProjectRoot "src\main.py") --background
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

