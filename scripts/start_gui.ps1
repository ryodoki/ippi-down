# Start the GUI with the project-local non-Conda Python 3.11 environment.
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Project environment not found. Run scripts\setup.ps1 first."
}

& $PythonExe -c "import struct, sys, tkinter; tcl = tkinter.Tcl(); valid = sys.version_info[:2] == (3, 11) and struct.calcsize('P') * 8 == 64 and all('conda' not in str(value).lower() for value in (sys.executable, sys.base_prefix)); raise SystemExit(0 if valid and tcl.eval('info patchlevel') else 1)" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Project .venv is stale, invalid, or Conda-based. Run scripts\setup.ps1."
}

Push-Location $ProjectRoot
try {
    & $PythonExe (Join-Path $ProjectRoot "src\main.py")
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
