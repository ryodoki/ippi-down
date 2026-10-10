@echo off
setlocal
REM 依存関係を再導入してから安全なPyInstallerビルドを実行
for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "BUILD_SCRIPT=%~dp0build_exe.bat"
pushd "%PROJECT_ROOT%"

echo ========================================
echo ippi-down 実行ファイル再ビルドスクリプト
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

echo.
echo 依存関係を再インストールしています...
"%PYTHON_EXE%" -m pip install -c requirements\constraints.txt -r requirements\build.txt
if errorlevel 1 (
    echo.
    echo エラー: 依存関係のインストールに失敗しました。
    echo 既存のexeと利用者データは変更していません。
    popd
    exit /b 1
)

popd
REM distを削除しない安全なビルド処理はbuild_exe.batへ集約する。
call "%BUILD_SCRIPT%"
exit /b %ERRORLEVEL%
