# Create a project-local Python 3.11 environment without Conda.
[CmdletBinding()]
param(
    [string]$PythonExe = "",
    [switch]$WithTest,
    [switch]$WithBuild,
    [switch]$WithTools,
    [switch]$WithWindowsNotification,
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

function Get-CompatiblePython {
    param([string]$Candidate)

    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
        return $null
    }

    $ResolvedCandidate = (Resolve-Path -LiteralPath $Candidate).Path
    if ($ResolvedCandidate -match "(?i)(?:mini)?conda|anaconda") {
        return $null
    }

    try {
        $Json = & $ResolvedCandidate -c @"
import json, struct, sys, tkinter
tcl = tkinter.Tcl()
print(json.dumps({
    "major": sys.version_info.major,
    "minor": sys.version_info.minor,
    "bits": struct.calcsize("P") * 8,
    "executable": sys.executable,
    "base_prefix": sys.base_prefix,
    "tcl": tcl.eval("info patchlevel"),
}))
"@ 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $Json) {
            return $null
        }
        $Info = $Json | ConvertFrom-Json
        if (
            $Info.major -ne 3 -or
            $Info.minor -ne 11 -or
            $Info.bits -ne 64 -or
            $Info.executable -match "(?i)(?:mini)?conda|anaconda" -or
            $Info.base_prefix -match "(?i)(?:mini)?conda|anaconda"
        ) {
            return $null
        }
        return $Info
    }
    catch {
        return $null
    }
}

function Get-ProjectVenvInfo {
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        return $null
    }
    return Get-CompatiblePython -Candidate $VenvPython
}

$SelectedPython = $null
if ($PythonExe) {
    $SelectedPython = Get-CompatiblePython -Candidate $PythonExe
    if ($null -eq $SelectedPython) {
        throw "-PythonExe must point to a non-Conda Windows x64 Python 3.11 executable."
    }
}
else {
    $Candidates = [System.Collections.Generic.List[string]]::new()

    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        try {
            $LauncherPython = & $Launcher.Source -3.11 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $LauncherPython) {
                $Candidates.Add($LauncherPython.Trim())
            }
        }
        catch {
            # Continue with the normal installation paths.
        }
    }

    $Candidates.Add(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe")
    )
    if ($env:ProgramFiles) {
        $Candidates.Add(
            (Join-Path $env:ProgramFiles "Python311\python.exe")
        )
    }
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCommand -and $PythonCommand.Source) {
        $Candidates.Add($PythonCommand.Source)
    }

    foreach ($Candidate in ($Candidates | Select-Object -Unique)) {
        $SelectedPython = Get-CompatiblePython -Candidate $Candidate
        if ($null -ne $SelectedPython) {
            break
        }
    }
}

if ($null -eq $SelectedPython) {
    throw @"
Windows x64 Python 3.11 was not found outside Conda.
Install Python 3.11 with Tcl/Tk support from python.org, enable the Python
launcher or PATH, then run this script again. Conda and Miniconda are
intentionally rejected.
"@
}

$ExistingVenv = Get-ProjectVenvInfo
if ($Recreate -or (
    (Test-Path -LiteralPath $VenvDir) -and $null -eq $ExistingVenv
)) {
    $BackupDir = Join-Path (
        [IO.Path]::GetTempPath()
    ) ("ippi-down-stale-venv-" + [guid]::NewGuid().ToString("N"))
    $ResolvedProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
    $ResolvedVenvDir = [IO.Path]::GetFullPath($VenvDir)
    if (-not $ResolvedVenvDir.StartsWith(
        $ResolvedProjectRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing to move a virtual environment outside the project root."
    }
    Write-Warning "Moving the stale project environment to: $BackupDir"
    Move-Item -LiteralPath $ResolvedVenvDir -Destination $BackupDir
    $ExistingVenv = $null
}

if ($null -eq $ExistingVenv) {
    Write-Host "Creating .venv with: $($SelectedPython.executable)" -ForegroundColor Cyan
    & $SelectedPython.executable -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the project virtual environment."
    }
}
else {
    Write-Host "Using the existing project Python 3.11 environment." -ForegroundColor Cyan
}

$VerifiedVenv = Get-ProjectVenvInfo
if ($null -eq $VerifiedVenv) {
    throw "The project virtual environment is not a usable non-Conda Python 3.11 environment."
}

$PipArguments = @(
    "-m", "pip", "install",
    "-c", (Join-Path $ProjectRoot "requirements\constraints.txt"),
    "-r", (Join-Path $ProjectRoot "requirements\runtime.txt")
)
if ($WithTest) {
    $PipArguments += @(
        "-r", (Join-Path $ProjectRoot "requirements\test.txt")
    )
}
if ($WithBuild) {
    $PipArguments += @(
        "-r", (Join-Path $ProjectRoot "requirements\build.txt")
    )
}
if ($WithTools) {
    $PipArguments += @(
        "-r", (Join-Path $ProjectRoot "requirements\tools.txt")
    )
}
if ($WithWindowsNotification) {
    $PipArguments += @(
        "-r", (Join-Path $ProjectRoot "requirements\windows-optional.txt")
    )
}

Write-Host "Installing project dependencies..." -ForegroundColor Cyan
& $VenvPython @PipArguments
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

& $VenvPython -c "import sys; print('Ready:', sys.executable); print(sys.version)"
if ($LASTEXITCODE -ne 0) {
    throw "The project Python verification failed."
}

Write-Host "Setup completed without Conda." -ForegroundColor Green
