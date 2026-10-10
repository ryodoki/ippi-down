@echo off
setlocal
REM Delegate to the project-root-aware PowerShell setup script.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
exit /b %ERRORLEVEL%
