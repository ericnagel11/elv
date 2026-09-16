#Requires -Version 5.1
<#
.SYNOPSIS
    Run a bounded count/query comparison for one or two approved Search indexes.
.DESCRIPTION
    Requires check-query.ps1 in the same folder. Default: two probes on one index.
    Optional second index and API comparison expand to at most eight probes.
    Query probes request zero documents; no models, mutations, automatic retries,
    role changes or authentication fallbacks. Run only on the approved Azure VM.
#>
[CmdletBinding()]
param(
    [string]$Endpoint,
    [string]$IndexName,
    [string]$ComparisonIndexName,
    [string]$ClientId,
    [switch]$ApprovedAzureHost,
    [switch]$CompareApiVersions
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$probePath = Join-Path $PSScriptRoot 'check-query.ps1'
if (-not $ApprovedAzureHost -or [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Write-Output 'HOST_REQUIRED: authorize this Azure Windows VM, identity and all supplied indexes with -ApprovedAzureHost.'
    exit 2
}
if (-not (Test-Path -LiteralPath $probePath -PathType Leaf)) {
    Write-Output 'PREREQUISITE_MISSING: copy the updated check-query.ps1 beside this diagnostic runner.'
    exit 2
}
# Inspect the companion's top-level signature without executing or dot-sourcing
# it. An older copied probe lacks Operation/ApiVersion and would fail binding
# after SEARCH_CASE, obscuring that no Azure request has started.
$probeCompatible = $false
try {
    $probeTokens = $null
    $probeParseErrors = $null
    $probeAst = [System.Management.Automation.Language.Parser]::ParseFile(
        $probePath, [ref]$probeTokens, [ref]$probeParseErrors
    )
    if ($probeParseErrors.Count -eq 0 -and $null -ne $probeAst.ParamBlock) {
        $probeParameters = @($probeAst.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
        $missingParameters = @(@(
            'Endpoint', 'IndexName', 'ClientId', 'ApprovedAzureHost',
            'Diagnostics', 'Operation', 'ApiVersion'
        ) | Where-Object { $probeParameters -notcontains $_ })
        $probeCompatible = $missingParameters.Count -eq 0
    }
}
catch { $probeCompatible = $false }
if (-not $probeCompatible) {
    Write-Output 'PROBE_VERSION_MISMATCH: the companion check-query.ps1 is outdated, incomplete or unreadable. Replace it with the updated Search probe supporting -Operation and -ApiVersion in the same folder as this runner. No Azure request was made.'
    exit 2
}
$indexes = @($IndexName)
if ($ComparisonIndexName -and $ComparisonIndexName -cne $IndexName) { $indexes += $ComparisonIndexName }
# Validate every target before starting any check, without reading index contents.
foreach ($index in $indexes) {
    if ($index -cnotmatch '\A[a-z0-9][a-z0-9_-]{0,126}[a-z0-9]\z' -or $index.Contains('--')) {
        Write-Output 'CONFIGURATION_ERROR: supply valid lowercase approved index names.'
        exit 2
    }
}
$versions = @('2026-04-01')
if ($CompareApiVersions) { $versions += '2024-07-01' }
$failed = $false
foreach ($index in $indexes) {
    foreach ($version in $versions) {
        foreach ($operation in @('Count', 'Query')) {
            Write-Output ('SEARCH_CASE: index={0}; operation={1}; api_version={2}' -f $index, $operation, $version)
            $global:LASTEXITCODE = 2
            & $probePath -Endpoint $Endpoint -IndexName $index -ClientId $ClientId `
                -ApprovedAzureHost -Diagnostics -Operation $operation -ApiVersion $version
            $caseCode = $global:LASTEXITCODE
            Write-Output ('SEARCH_CASE_RESULT: exit={0}' -f $caseCode)
            # Stop on local/prerequisite/login/cleanup error; do not repeat bad
            # authentication or continue while private credential cleanup failed.
            if ($caseCode -notin @(0, 4)) {
                Write-Output 'SEARCH_COMPARISON_STOPPED: resolve the host, identity or cleanup error before further checks.'
                exit $caseCode
            }
            if ($caseCode -ne 0) { $failed = $true }
        }
    }
}
if ($failed) {
    Write-Output 'SEARCH_COMPARISON_COMPLETE: at least one check failed; retain the case and correlation summaries for investigation.'
    exit 4
}
Write-Output 'SEARCH_COMPARISON_COMPLETE: all selected checks passed; full PoC and document-level permissions are not validated.'
exit 0