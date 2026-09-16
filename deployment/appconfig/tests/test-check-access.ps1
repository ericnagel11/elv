#Requires -Version 5.1
<#
.SYNOPSIS
    Offline regression tests for the Windows probe's native exit-code handling.
.DESCRIPTION
    Loads only Invoke-ProbeAz from the parsed source and uses a harmless local
    batch fixture, never Azure CLI, IMDS, tokens, or the complete probe script.
    Run normally with &, not by dot-sourcing. No Pester installation is needed.
#>
[CmdletBinding()]
param(
    [string]$ProbePath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'check-access.ps1')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'These native-command regression tests require Windows.'
}

$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $ProbePath, [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw 'The Windows probe has PowerShell syntax errors.'
}
$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Invoke-ProbeAz'
}, $true)
if (-not $functionAst) {
    throw 'Invoke-ProbeAz was not found in the probe.'
}
# Define just the production wrapper in this test scope, not the probe body.
. ([scriptblock]::Create($functionAst.Extent.Text))

function Assert-Code {
    param([object[]]$Actual, [int]$Expected, [string]$Case)
    if ($Actual.Count -ne 1 -or $Actual[0] -ne $Expected) {
        throw "$Case failed: expected one exit code ($Expected), with no command output."
    }
    Write-Output "PASS: $Case"
}

function Invoke-WithShadowedExitCode {
    param([string]$ErrorFile)
    $local:LASTEXITCODE = 99
    Invoke-ProbeAz -Arguments @('0') -ErrorFile $ErrorFile
}

$savedExitCode = Get-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
$savedExitCodeValue = if ($null -ne $savedExitCode) { $savedExitCode.Value } else { $null }
$scratch = Join-Path ([System.IO.Path]::GetTempPath()) (
    'elv probe test ' + [Guid]::NewGuid().ToString('N')
)
try {
    New-Item -ItemType Directory -Path $scratch | Out-Null
    $errorFile = Join-Path $scratch 'native-error.txt'
    $azCommand = Get-Command (Join-Path $PSScriptRoot 'fixtures\native-command.cmd') -CommandType Application

    $result = @(Invoke-ProbeAz -Arguments @('0') -ErrorFile $errorFile)
    Assert-Code -Actual $result -Expected 0 -Case 'Successful native command'
    if ((Get-Content -LiteralPath $errorFile -Raw) -notmatch 'ELV_TEST_STDERR') {
        throw 'Native stderr was not captured in the designated file.'
    }
    Write-Output 'PASS: Native stdout suppressed and stderr captured'

    $result = @(Invoke-ProbeAz -Arguments @('17') -ErrorFile $errorFile)
    Assert-Code -Actual $result -Expected 17 -Case 'Nonzero native command'

    $result = @(Invoke-ProbeAz -Arguments @('0') -ErrorFile $errorFile)
    Assert-Code -Actual $result -Expected 0 -Case 'Success after failure'

    $result = @(Invoke-WithShadowedExitCode -ErrorFile $errorFile)
    Assert-Code -Actual $result -Expected 0 -Case 'Caller local variable cannot shadow native result'

    # A launch failure immediately after a success must not return stale zero.
    $azCommand = [pscustomobject]@{ Source = (Join-Path $scratch 'missing-command.cmd') }
    try {
        $result = @(Invoke-ProbeAz -Arguments @() -ErrorFile $errorFile)
        Assert-Code -Actual $result -Expected 1 -Case 'Launch failure does not reuse success'
    }
    catch [System.Management.Automation.CommandNotFoundException] {
        Write-Output 'PASS: Launch failure throws rather than returning stale success'
    }
    if ($ErrorActionPreference -ne 'Stop') {
        throw 'The wrapper changed the caller error preference.'
    }
    Write-Output 'PASS: Caller error preference preserved'
}
finally {
    if (Test-Path -LiteralPath $scratch) {
        Remove-Item -LiteralPath $scratch -Recurse -Force
    }
    if ($null -ne $savedExitCode) {
        $global:LASTEXITCODE = $savedExitCodeValue
    }
    else {
        Remove-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    }
}