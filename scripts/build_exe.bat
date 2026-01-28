@echo off
REM PyInstallerを使用して実行ファイルをビルド

echo ========================================
echo ippi-down 実行ファイルビルドスクリプト
echo ========================================
echo.

REM 仮想環境の有効化
if exist .venv\Scripts\activate.bat (
    echo 仮想環境を有効化しています...
    call .venv\Scripts\activate.bat
) else (
    echo 警告: 仮想環境が見つかりません
    echo 仮想環境を作成してください: python -m venv .venv
    pause
    exit /b 1
)

REM PyInstallerのインストール確認
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstallerをインストールしています...
    pip install pyinstaller
)

REM ビルドディレクトリのクリーンアップ
if exist build (
    echo 既存のビルドディレクトリを削除しています...
    rmdir /s /q build
)
if exist dist (
    echo 既存のdistディレクトリを削除しています...
    rmdir /s /q dist
)

REM PyInstallerで実行ファイルをビルド
echo.
echo 実行ファイルをビルドしています...
echo これには数分かかる場合があります...
echo.
pyinstaller scripts\build.spec

if errorlevel 1 (
    echo.
    echo エラー: ビルドに失敗しました
    pause
    exit /b 1
)

echo.
echo ========================================
echo ビルドが完了しました！
echo ========================================
echo.
echo 実行ファイルの場所: dist\ippi-down.exe
echo.

pause

