@echo off
setlocal
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Project environment not found. Run scripts\setup.bat first.
    exit /b 1
)

"%PYTHON_EXE%" -c "import struct,sys,tkinter;tcl=tkinter.Tcl();valid=sys.version_info[:2]==(3,11) and struct.calcsize('P')*8==64 and all('conda' not in str(v).lower() for v in (sys.executable,sys.base_prefix));raise SystemExit(0 if valid and tcl.eval('info patchlevel') else 1)" >nul 2>nul
if errorlevel 1 (
    echo Project .venv is stale, invalid, or Conda-based. Run scripts\setup.bat.
    exit /b 1
)

pushd "%PROJECT_ROOT%"
"%PYTHON_EXE%" "%PROJECT_ROOT%\src\main.py"
set "APP_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %APP_EXIT_CODE%
