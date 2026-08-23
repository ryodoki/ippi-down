#Requires -Version 5.1
<#
.SYNOPSIS
  ippi-down の定期実行タスクをタスクスケジューラから削除する。
.EXAMPLE
  .\unregister_task.ps1 -TaskName ippi-down-daily
#>

[CmdletBinding()]
param(
    [string]$TaskName = "ippi-down-daily"
)

$ErrorActionPreference = "Stop"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "タスクは登録されていません: $TaskName" -ForegroundColor Yellow
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "タスクを削除しました: $TaskName" -ForegroundColor Green
