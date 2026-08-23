@echo off
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo .venv が見つかりません。先に python -m venv .venv を実行してください。
    pause
    exit /b 1
)
python src/main.py
pause
