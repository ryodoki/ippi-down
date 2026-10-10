@echo off
setlocal
REM ippi-down バックグラウンド実行（配置場所を基準にプロジェクトを解決）

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo エラー: 仮想環境が見つかりません: "%PYTHON_EXE%"
    echo scripts\setup.bat を先に実行してください。
    exit /b 1
)

"%PYTHON_EXE%" -c "import struct,sys;valid=sys.version_info[:2]==(3,11) and struct.calcsize('P')*8==64 and all('conda' not in str(v).lower() for v in (sys.executable,sys.base_prefix));raise SystemExit(0 if valid else 1)" >nul 2>nul
if errorlevel 1 (
    echo エラー: .venvが壊れているか、Python 3.11 x64以外またはCondaを参照しています。
    echo scripts\setup.bat で再作成してください。
    exit /b 1
)

pushd "%PROJECT_ROOT%"
set "PPI_BACKGROUND_MODE=true"
"%PYTHON_EXE%" "%PROJECT_ROOT%\src\main.py" --background
set "APP_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %APP_EXIT_CODE%

