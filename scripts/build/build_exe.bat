@echo off
setlocal
REM PyInstallerを使用して実行ファイルを安全にビルド（プロジェクト外からも実行可）
for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "BUILD_DIR=%PROJECT_ROOT%\build"
set "WORK_DIR=%BUILD_DIR%\pyinstaller-work"
set "STAGED_DIST=%BUILD_DIR%\staged-dist"
set "STAGED_EXE=%STAGED_DIST%\ippi-down.exe"
set "DIST_DIR=%PROJECT_ROOT%\dist"
set "TARGET_EXE=%DIST_DIR%\ippi-down.exe"
pushd "%PROJECT_ROOT%"

echo ========================================
echo ippi-down 実行ファイルビルドスクリプト
echo ========================================
echo.

if not exist "%PYTHON_EXE%" (
    echo エラー: 仮想環境が見つかりません: "%PYTHON_EXE%"
    echo scripts\setup.bat -WithBuild を先に実行してください。
    popd
    exit /b 1
)

"%PYTHON_EXE%" -c "import struct,sys,tkinter;tcl=tkinter.Tcl();valid=sys.version_info[:2]==(3,11) and struct.calcsize('P')*8==64 and all('conda' not in str(v).lower() for v in (sys.executable,sys.base_prefix));raise SystemExit(0 if valid and tcl.eval('info patchlevel') else 1)" >nul 2>nul
if errorlevel 1 (
    echo エラー: .venvが壊れているか、Tk対応Python 3.11 x64以外またはCondaを参照しています。
    echo scripts\setup.bat -WithBuild で再作成してください。
    popd
    exit /b 1
)

"%PYTHON_EXE%" -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo エラー: PyInstallerがありません。
    echo "%PYTHON_EXE%" -m pip install -c requirements\constraints.txt -r requirements\build.txt
    popd
    exit /b 1
)

REM buildは中間物専用。distには利用者データがあるためディレクトリ削除禁止。
if exist "%BUILD_DIR%" (
    echo 既存のビルドディレクトリを削除しています...
    rmdir /s /q "%BUILD_DIR%"
    if errorlevel 1 (
        echo エラー: buildディレクトリを削除できません。
        popd
        exit /b 1
    )
)

echo.
echo 一時出力へ実行ファイルをビルドしています...
echo これには数分かかる場合があります...
echo.
"%PYTHON_EXE%" -m PyInstaller --noconfirm --workpath "%WORK_DIR%" --distpath "%STAGED_DIST%" scripts\build\build.spec

if errorlevel 1 (
    echo.
    echo エラー: ビルドに失敗しました。
    echo 既存のdist\ippi-down.exeと利用者データは変更していません。
    popd
    exit /b 1
)
if not exist "%STAGED_EXE%" (
    echo エラー: 一時出力にippi-down.exeがありません。既存のexeは変更していません。
    popd
    exit /b 1
)

REM 成功終了だけでなく、正サイズとWindows exe署名を確認してから置換する。
"%PYTHON_EXE%" -c "from pathlib import Path;import sys;p=Path(sys.argv[1]);raise SystemExit(0 if p.stat().st_size>0 and p.open('rb').read(2)==b'MZ' else 1)" "%STAGED_EXE%"
if errorlevel 1 (
    echo エラー: 生成されたippi-down.exeの検証に失敗しました。既存のexeは変更していません。
    popd
    exit /b 1
)

if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if not exist "%DIST_DIR%" (
    echo エラー: distディレクトリを作成できません。既存のexeは変更していません。
    popd
    exit /b 1
)

REM os.replaceは同一ボリューム内でexeだけを原子的に置換する。
REM 実行中のexeはWindowsのロックにより失敗し、旧exeがそのまま残る。
"%PYTHON_EXE%" -c "import os,sys;os.replace(sys.argv[1],sys.argv[2])" "%STAGED_EXE%" "%TARGET_EXE%"
if errorlevel 1 (
    echo エラー: dist\ippi-down.exeを置換できません。
    echo アプリを終了して再実行してください。旧exeと利用者データは保持されています。
    popd
    exit /b 1
)

echo.
echo ========================================
echo ビルドが完了しました！
echo ========================================
echo.
echo 実行ファイルの場所: dist\ippi-down.exe
echo dist内のconfig、downloads、logsなどは変更していません。
echo.

popd
exit /b 0
