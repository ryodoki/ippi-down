@echo off
REM ppi-file-downloader バックグラウンド実行用バッチファイル
REM PC起動時に自動実行する場合は、このファイルをスタートアップに登録してください

cd /d "%~dp0"
python src\main.py --background

