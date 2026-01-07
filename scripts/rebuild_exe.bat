@echo off
REM PyInstallerを使用して実行ファイルを再ビルド（依存関係を再インストール）

echo ========================================
echo ippi-down 実行ファイル再ビルドスクリプト
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

REM 依存関係を再インストール
echo.
echo 依存関係を再インストールしています...
pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo エラー: 依存関係のインストールに失敗しました
    pause
    exit /b 1
)

REM ビルドディレクトリのクリーンアップ
echo.
echo 既存のビルド成果物をクリーンアップしています...
if exist build (
    rmdir /s /q build
)
if exist dist (
    rmdir /s /q dist
)

REM PyInstallerで実行ファイルをビルド
echo.
echo 実行ファイルをビルドしています...
echo これには数分かかる場合があります...
echo.
pyinstaller build.spec

if errorlevel 1 (
    echo.
    echo エラー: ビルドに失敗しました
    pause
    exit /b 1
)

echo.
echo ========================================
echo 再ビルドが完了しました！
echo ========================================
echo.
echo 実行ファイルの場所: dist\ippi-down.exe
echo.

pause

