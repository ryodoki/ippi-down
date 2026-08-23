#Requires -Version 5.1
<#
.SYNOPSIS
  ippi-down の定期実行タスクの状態と直近の実行履歴を表示する。
.EXAMPLE
  .\status_task.ps1 -TaskName ippi-down-daily
#>

[CmdletBinding()]
param(
    [string]$TaskName = "ippi-down-daily",
    [int]$HistoryLines = 10
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "タスクは登録されていません: $TaskName" -ForegroundColor Yellow
} else {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "タスク名        : $TaskName"
    Write-Host "状態            : $($task.State)"
    Write-Host "前回実行        : $($info.LastRunTime)"
    Write-Host "前回の実行結果  : $($info.LastTaskResult)（0 なら成功）"
    Write-Host "次回実行予定    : $($info.NextRunTime)"
}

$historyPath = Join-Path $projectRoot "logs\batch-history.log"
if (Test-Path $historyPath) {
    Write-Host ""
    Write-Host "実行履歴（直近 $HistoryLines 件、開始/終了/exit/タスク/-/レポート）:" -ForegroundColor Cyan
    Get-Content $historyPath -Tail $HistoryLines | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host ""
    Write-Host "実行履歴はまだありません: $historyPath"
}
