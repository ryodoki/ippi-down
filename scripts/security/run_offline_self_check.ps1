# Run the packaged self-check while Windows Firewall blocks its executable and
# the exact Microsoft Edge binary from making outbound connections.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$ErrorActionPreference = "Stop"
$ResolvedExe = (Resolve-Path -LiteralPath $ExePath -ErrorAction Stop).Path
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
if (-not $Principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)) {
    throw "The offline self-check requires an elevated Windows CI runner."
}

$EdgeCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
    (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
    (Join-Path $env:LOCALAPPDATA "Microsoft\Edge\Application\msedge.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
if (-not $EdgeCandidates) {
    throw "Microsoft Edge was not found for the offline self-check."
}
$ResolvedEdge = (Resolve-Path -LiteralPath $EdgeCandidates[0]).Path

$RuleNames = [System.Collections.Generic.List[string]]::new()
$RulePrefix = "ippi-down-ci-offline-" + [guid]::NewGuid().ToString("N")
try {
    $Programs = @($ResolvedExe, $ResolvedEdge) | Select-Object -Unique
    for ($Index = 0; $Index -lt $Programs.Count; $Index++) {
        $RuleName = "$RulePrefix-$Index"
        New-NetFirewallRule `
            -Name $RuleName `
            -DisplayName $RuleName `
            -Direction Outbound `
            -Action Block `
            -Program $Programs[$Index] `
            -Profile Any `
            -Enabled True | Out-Null
        $RuleNames.Add($RuleName)
    }

    $SelfCheck = Start-Process `
        -FilePath $ResolvedExe `
        -ArgumentList "--self-check" `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($SelfCheck.ExitCode -ne 0) {
        throw "Offline exe self-check failed with exit code $($SelfCheck.ExitCode)."
    }
}
finally {
    foreach ($RuleName in $RuleNames) {
        Remove-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
    }
}
