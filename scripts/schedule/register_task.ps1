#Requires -Version 5.1
<#
.SYNOPSIS
  ippi-down の定期実行タスクをタスクスケジューラに登録する。
.DESCRIPTION
  run_batch.ps1 を指定スケジュールで起動するタスクを登録します。
  設定の network.allowed_hours が指定時刻を含まない場合は警告します
  （範囲外だとアプリ側のポリシーで実行が停止するため）。
  管理者権限で実行した場合は、失敗通知用のイベントログソースも登録します。
.EXAMPLE
  .\register_task.ps1 -Time "09:30" -Interval Daily
#>

[CmdletBinding()]
param(
    [string]$TaskName = "ippi-down-daily",
    [ValidatePattern("^\d{1,2}:\d{2}$")]
    [string]$Time = "09:30",
    [ValidateSet("Daily", "Weekly", "Hourly")]
    [string]$Interval = "Daily",
    [ValidateSet("Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday")]
    [string]$DayOfWeek = "Monday",
    [string]$ConfigPath = $null,
    [int]$ExecutionTimeLimitHours = 4
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$runnerPath = Join-Path $PSScriptRoot "run_batch.ps1"
if (-not (Test-Path $runnerPath)) {
    Write-Error "ランナーが見つかりません: $runnerPath"
}

# --- allowed_hours との整合チェック（警告のみ） ---
$effectiveConfig = if ($ConfigPath) { $ConfigPath } else { Join-Path $projectRoot "config\config.yaml" }
if (Test-Path $effectiveConfig) {
    $text = Get-Content $effectiveConfig -Raw -Encoding UTF8
    if ($text -match "allowed_hours:\s*['`"]?(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})") {
        $rangeStart = [datetime]::ParseExact($Matches[1], "H:mm", $null).TimeOfDay
        $rangeEnd = [datetime]::ParseExact($Matches[2], "H:mm", $null).TimeOfDay
        $runAt = [datetime]::ParseExact($Time, "H:mm", $null).TimeOfDay
        $inside = if ($rangeStart -le $rangeEnd) {
            ($runAt -ge $rangeStart) -and ($runAt -le $rangeEnd)
        } else {
            ($runAt -ge $rangeStart) -or ($runAt -le $rangeEnd)
        }
        if (-not $inside) {
            Write-Warning ("指定時刻 {0} は network.allowed_hours（{1}-{2}）の範囲外です。この時刻に実行してもアプリ側のポリシーで停止します。" -f $Time, $Matches[1], $Matches[2])
        }
    }
}

# --- 起動コマンドの組み立て ---
$runnerArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerPath`" -TaskName `"$TaskName`""
if ($ConfigPath) {
    $resolvedConfig = (Resolve-Path $ConfigPath).Path
    $runnerArgs += " -ConfigPath `"$resolvedConfig`""
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $runnerArgs

# --- トリガー ---
$startTime = [datetime]::ParseExact($Time, "H:mm", $null)
switch ($Interval) {
    "Daily"  { $trigger = New-ScheduledTaskTrigger -Daily -At $startTime }
    "Weekly" { $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $startTime }
    "Hourly" {
        $trigger = New-ScheduledTaskTrigger -Once -At $startTime `
            -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
    }
}

# --- 設定: 多重起動禁止・失敗時リトライ・起動遅延時の追い付き実行 ---
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 10) `
    -ExecutionTimeLimit (New-TimeSpan -Hours $ExecutionTimeLimitHours)

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "既存タスクを更新します: $TaskName" -ForegroundColor Yellow
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings | Out-Null
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description "ippi-down 定期バッチ（scripts/schedule/register_task.ps1 により登録）" | Out-Null
}

# --- イベントログソースの登録（管理者権限時のみ） ---
try {
    if (-not [System.Diagnostics.EventLog]::SourceExists($TaskName)) {
        New-EventLog -LogName Application -Source $TaskName
        Write-Host "イベントログソースを登録しました: $TaskName"
    }
} catch {
    Write-Warning "イベントログソースを登録できませんでした（管理者権限で再実行すると失敗通知が有効になります）"
}

Write-Host "タスクを登録しました: $TaskName ($Interval $Time)" -ForegroundColor Green
Write-Host "状態確認: .\status_task.ps1 -TaskName `"$TaskName`""
