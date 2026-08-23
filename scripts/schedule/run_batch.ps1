#Requires -Version 5.1
<#
.SYNOPSIS
  ippi-down をバッチ実行する（タスクスケジューラ用ランナー）。
.DESCRIPTION
  venv の python で CLI（--once）を実行し、実行サマリーを logs\reports\ に JSON で残します。
  開始/終了/終了コードを logs\batch-history.log に TSV で追記し、失敗時は
  Windows イベントログ（ソースが登録済みの場合のみ）にも書き込みます。
  設定の network.allowed_hours が現在時刻の範囲外の場合は、実行前に警告します
  （実行自体はアプリ側のポリシーで停止します）。
.EXAMPLE
  .\run_batch.ps1 -ConfigPath ..\..\config\config.yaml
#>

[CmdletBinding()]
param(
    [string]$ConfigPath = $null,
    [string]$PythonPath = $null,
    [string]$TaskName = "ippi-down-batch",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $projectRoot

function Write-History {
    param([string]$Line)
    $historyPath = Join-Path $projectRoot "logs\batch-history.log"
    New-Item -ItemType Directory -Path (Split-Path -Parent $historyPath) -Force | Out-Null
    Add-Content -Path $historyPath -Value $Line -Encoding UTF8
}

function Write-FailureEvent {
    param([string]$Message)
    # イベントソースは register_task.ps1（管理者権限時）で登録される。
    # 未登録や権限不足（SourceExists は Security ログも走査するため非管理者だと例外になる）
    # の場合は通知を諦めて静かにスキップする
    try {
        Write-EventLog -LogName Application -Source $TaskName -EntryType Error -EventId 1001 -Message $Message -ErrorAction Stop
    } catch {
        Write-Verbose "イベントログへの書き込みをスキップしました: $($_.Exception.Message)"
    }
}

function Test-AllowedHours {
    param([string]$ConfigFile)
    # network.allowed_hours（例 "08:00-22:00"）と現在時刻の整合を確認し、範囲外なら警告する
    if (-not (Test-Path $ConfigFile)) { return }
    $text = Get-Content $ConfigFile -Raw -Encoding UTF8
    if ($text -match "allowed_hours:\s*['`"]?(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})") {
        $rangeStart = [datetime]::ParseExact($Matches[1], "H:mm", $null).TimeOfDay
        $rangeEnd = [datetime]::ParseExact($Matches[2], "H:mm", $null).TimeOfDay
        $now = (Get-Date).TimeOfDay
        $inside = if ($rangeStart -le $rangeEnd) {
            ($now -ge $rangeStart) -and ($now -le $rangeEnd)
        } else {
            ($now -ge $rangeStart) -or ($now -le $rangeEnd)
        }
        if (-not $inside) {
            Write-Warning ("現在時刻が network.allowed_hours（{0}-{1}）の範囲外です。アプリ側のポリシーで実行が停止します。タスクの実行時刻を見直してください。" -f $Matches[1], $Matches[2])
        }
    }
}

try {
    # --- Python の解決 ---
    $python = $PythonPath
    if (-not $python) {
        $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path $python)) { $python = "python" }
    }

    # --- 事前チェック ---
    $effectiveConfig = if ($ConfigPath) { $ConfigPath } else { Join-Path $projectRoot "config\config.yaml" }
    if (-not (Test-Path $effectiveConfig)) {
        Write-Error "設定ファイルが見つかりません: $effectiveConfig"
    }
    Test-AllowedHours $effectiveConfig

    # --- 実行 ---
    $startedAt = Get-Date
    $stamp = $startedAt.ToString("yyyyMMdd_HHmmss")
    $reportPath = Join-Path $projectRoot "logs\reports\batch_$stamp.json"
    New-Item -ItemType Directory -Path (Split-Path -Parent $reportPath) -Force | Out-Null

    $cliArgs = @("src\cli\main.py", "--once", "--report", $reportPath)
    if ($ConfigPath) { $cliArgs += @("--config", $ConfigPath) }
    if ($DryRun)     { $cliArgs += "--dry-run" }

    Write-Host "バッチ実行を開始します: $python $($cliArgs -join ' ')"
    & $python @cliArgs
    $exitCode = $LASTEXITCODE

    $endedAt = Get-Date
    $line = ($startedAt.ToString("s"), $endedAt.ToString("s"), $exitCode, $TaskName, "-", $reportPath) -join "`t"
    Write-History $line

    if ($exitCode -ne 0) {
        $message = "ippi-down のバッチ実行が失敗しました (exit=$exitCode, report=$reportPath)"
        Write-Warning $message
        Write-FailureEvent $message
    } else {
        Write-Host "バッチ実行が完了しました (report: $reportPath)" -ForegroundColor Green
    }
    exit $exitCode
}
catch {
    $message = "ippi-down のバッチランナーがエラーで停止しました: $($_.Exception.Message)"
    Write-History ((Get-Date).ToString("s") + "`t-`t99`t$TaskName`t-`trunner-error")
    Write-FailureEvent $message
    Write-Error $message -ErrorAction Continue
    exit 99
}
finally {
    Pop-Location
}
