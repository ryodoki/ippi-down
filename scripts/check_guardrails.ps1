#Requires -Version 5.1
<#
.SYNOPSIS
  通信ガードレールのテストだけを高速に実行する（ローカル確認用）。
.DESCRIPTION
  静的検査（requests/socket の使用箇所・shell=True）と、エグレスガード・URLポリシー・
  robots.txt・レート制限・設定検証・監査ログのテストを実行します。
#>

[CmdletBinding()]
param(
    [switch]$StaticOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot

try {
    $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) { $python = "python" }

    $staticTests = @("tests/test_network_static.py")
    $runtimeTests = @(
        "tests/test_netguard.py",
        "tests/test_url_policy.py",
        "tests/test_robots.py",
        "tests/test_rate_limiter.py",
        "tests/test_shared_rate_limiter.py",
        "tests/test_config_network.py",
        "tests/test_audit_log.py"
    )

    $targets = if ($StaticOnly) { $staticTests } else { $staticTests + $runtimeTests }

    Write-Host "通信ガードレールの検証を開始します" -ForegroundColor Cyan
    Write-Host ("対象: " + ($targets -join ", "))

    & $python -m pytest @targets -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ガードレールの検証に失敗しました" -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "ガードレールの検証に成功しました（許可先のみ・作法つき）" -ForegroundColor Green
}
finally {
    Pop-Location
}
