#Requires -Version 5.1
<#
.SYNOPSIS
    Offline tests: fixed request, approval gates, mocked CLI, cleanup and errors.
.DESCRIPTION
    Never invokes real Azure CLI or any network API. Get-Command is intercepted
    in this script scope so the probe can resolve only a harmless batch fixture.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'These offline tests require Windows.'
}
$probePath = Join-Path (Split-Path $PSScriptRoot -Parent) 'check-inference.ps1'
$fixturePath = Join-Path $PSScriptRoot 'fixtures\az-mock.cmd'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $probePath, [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) { throw 'The inference probe has syntax errors.' }
foreach ($functionName in @('New-InferenceRequest', 'Get-InferenceFailureMessage')) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if (-not $functionAst) { throw 'A required production helper was not found.' }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

function Assert {
    param([bool]$Condition, [string]$Case)
    if (-not $Condition) { throw "FAIL: $Case" }
    Write-Output "PASS: $Case"
}

# Fail closed: no fallback to the real az executable, even if gates regress.
function Get-Command {
    param([string]$Name, [string]$CommandType, [string]$ErrorAction)
    if ($Name -ne 'az' -or $CommandType -ne 'Application') {
        throw 'Unexpected executable lookup in offline test.'
    }
    [pscustomobject]@{ Source = $fixturePath }
}

$settings = @{
    Endpoint = 'https://elv-test.openai.azure.com/'
    Deployment = 'test-deployment'
    ClientId = '11111111-1111-1111-1111-111111111111'
}
$savedEnvironment = @{}
foreach ($name in @(
    'ELV_OPENAI_TEST_LOG', 'ELV_OPENAI_TEST_LOGIN_EXIT',
    'ELV_OPENAI_TEST_REST_EXIT', 'ELV_OPENAI_TEST_REST_ERROR',
    'AZURE_CONFIG_DIR', 'NO_PROXY', 'OPENAI_API_KEY'
)) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$savedExitCode = Get-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
$savedExitValue = if ($null -ne $savedExitCode) { $savedExitCode.Value } else { $null }
$scratch = Join-Path ([System.IO.Path]::GetTempPath()) ('elv inference test ' + [Guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $scratch | Out-Null
    $env:ELV_OPENAI_TEST_LOG = Join-Path $scratch 'calls.txt'
    $env:ELV_OPENAI_TEST_LOGIN_EXIT = '0'
    $env:ELV_OPENAI_TEST_REST_EXIT = '0'
    $env:ELV_OPENAI_TEST_REST_ERROR = 'ELV_TEST_RAW_DIAGNOSTIC'
    $env:AZURE_CONFIG_DIR = Join-Path $scratch 'caller-cache'
    $env:NO_PROXY = 'corp.example.test'
    $env:OPENAI_API_KEY = 'ELV_TEST_NOT_A_REAL_KEY'

    $request = New-InferenceRequest -Endpoint $settings.Endpoint -Deployment $settings.Deployment
    $body = $request.Body | ConvertFrom-Json
    Assert ($request.Url -eq 'https://elv-test.openai.azure.com/openai/deployments/test-deployment/chat/completions?api-version=2024-10-21') 'Deployment URL and fixed API version'
    Assert ($body.messages.Count -eq 1 -and $body.messages[0].role -eq 'user' -and $body.messages[0].content -eq 'Reply with OK.' -and $body.max_tokens -eq 16 -and $body.n -eq 1 -and $body.stream -eq $false) 'Fixed synthetic prompt and output limit'

    foreach ($badEndpoint in @(
        'http://elv-test.openai.azure.com', 'https://example.com',
        'https://elv-test.openai.azure.com.evil.example',
        'https://elv-test.openai.azure.com/openai',
        'https://user:password@elv-test.openai.azure.com',
        'https://elv-test.openai.azure.com?key=bad'
    )) {
        $rejected = $false
        try { $null = New-InferenceRequest -Endpoint $badEndpoint -Deployment 'test' }
        catch { $rejected = $true }
        Assert $rejected 'Unsafe endpoint rejected'
    }
    foreach ($badDeployment in @('', '../test', 'test?x=y', 'test&other', ('a' * 65))) {
        $rejected = $false
        try { $null = New-InferenceRequest -Endpoint $settings.Endpoint -Deployment $badDeployment }
        catch { $rejected = $true }
        Assert $rejected 'Unsafe deployment rejected'
    }

    $output = @(& $probePath @settings -AllowInference)
    Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'HOST_REQUIRED:*' -and -not (Test-Path $env:ELV_OPENAI_TEST_LOG)) 'Host approval required before CLI'
    $output = @(& $probePath @settings -ApprovedAzureHost)
    Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'INFERENCE_APPROVAL_REQUIRED:*' -and -not (Test-Path $env:ELV_OPENAI_TEST_LOG)) 'Inference cost approval required before CLI'
    $badIdentity = $settings.Clone()
    $badIdentity.ClientId = '00000000-0000-0000-0000-000000000000'
    $output = @(& $probePath @badIdentity -ApprovedAzureHost -AllowInference)
    Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'CONFIGURATION_ERROR:*' -and -not (Test-Path $env:ELV_OPENAI_TEST_LOG)) 'Invalid identity rejected before CLI'

    $output = @(& $probePath @settings -ApprovedAzureHost -AllowInference)
    Assert ($global:LASTEXITCODE -eq 0 -and $output[0] -like 'INFERENCE_SUCCEEDED:*') 'Mocked successful login and inference'
    $callLog = Get-Content -LiteralPath $env:ELV_OPENAI_TEST_LOG -Raw
    $calls = @(Get-Content -LiteralPath $env:ELV_OPENAI_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
    Assert ($calls.Count -eq 2 -and $calls[0] -match 'login --identity --client-id 11111111-1111-1111-1111-111111111111' -and $calls[1] -match 'rest --method post' -and $calls[1] -match '--resource https://cognitiveservices.azure.com/' -and $calls[1] -match '--output none') 'Only explicit identity login and authenticated POST'
    Assert ($callLog.Contains($request.Body)) 'Native body file contains the fixed JSON payload'
    Assert (($output -join "`n") -notmatch 'ELV_TEST_|access_token|Bearer') 'No raw diagnostics or model output displayed'
    Assert ($env:AZURE_CONFIG_DIR -eq (Join-Path $scratch 'caller-cache') -and $env:NO_PROXY -eq 'corp.example.test' -and $env:OPENAI_API_KEY -eq 'ELV_TEST_NOT_A_REAL_KEY') 'Caller environment restored after success'
    Assert ($callLog -match 'BYPASS\|corp.example.test,169.254.169.254,127.0.0.1,localhost') 'Existing proxy bypasses preserved'
    foreach ($line in (Get-Content -LiteralPath $env:ELV_OPENAI_TEST_LOG | Where-Object { $_ -like 'CACHE|*' })) {
        $cacheParent = Split-Path $line.Substring(6) -Parent
        Assert (-not (Test-Path -LiteralPath $cacheParent)) 'Private probe files removed'
    }

    Remove-Item -LiteralPath $env:ELV_OPENAI_TEST_LOG
    $env:ELV_OPENAI_TEST_LOGIN_EXIT = '7'
    $output = @(& $probePath @settings -ApprovedAzureHost -AllowInference)
    $calls = @(Get-Content -LiteralPath $env:ELV_OPENAI_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
    Assert ($global:LASTEXITCODE -eq 3 -and $output[0] -like 'IDENTITY_LOGIN_FAILED:*' -and $calls.Count -eq 1) 'Failed login prevents inference'

    $env:ELV_OPENAI_TEST_LOGIN_EXIT = '0'
    $env:ELV_OPENAI_TEST_REST_EXIT = '8'
    foreach ($case in @(
        @{ Detail = '403 Forbidden ELV_TEST_RAW_DIAGNOSTIC'; Prefix = 'INFERENCE_FORBIDDEN:' },
        @{ Detail = '401 Unauthorized'; Prefix = 'INFERENCE_AUTHENTICATION_FAILED:' },
        @{ Detail = '404 DeploymentNotFound'; Prefix = 'INFERENCE_NOT_FOUND:' },
        @{ Detail = '429 TooManyRequests'; Prefix = 'INFERENCE_THROTTLED:' },
        @{ Detail = 'SSL certificate verify failed'; Prefix = 'INFERENCE_CONNECTIVITY_FAILED:' },
        @{ Detail = '400 Bad Request'; Prefix = 'INFERENCE_REQUEST_REJECTED:' },
        @{ Detail = 'ELV_TEST_RAW_DIAGNOSTIC'; Prefix = 'INFERENCE_FAILED:' }
    )) {
        $env:ELV_OPENAI_TEST_REST_ERROR = $case.Detail
        $output = @(& $probePath @settings -ApprovedAzureHost -AllowInference)
        Assert ($global:LASTEXITCODE -eq 4 -and $output[0].StartsWith($case.Prefix) -and ($output -join "`n") -notmatch 'ELV_TEST_') ('Sanitized failure category ' + $case.Prefix)
        Assert ($env:AZURE_CONFIG_DIR -eq (Join-Path $scratch 'caller-cache') -and $env:OPENAI_API_KEY -eq 'ELV_TEST_NOT_A_REAL_KEY') 'Caller environment restored after failure'
    }
    foreach ($line in (Get-Content -LiteralPath $env:ELV_OPENAI_TEST_LOG | Where-Object { $_ -like 'CACHE|*' })) {
        if (Test-Path -LiteralPath (Split-Path $line.Substring(6) -Parent)) {
            throw 'A private probe directory survived a mocked failure.'
        }
    }
    Write-Output 'PASS: Private probe files removed on failure paths'
}
finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
    if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force }
    if ($null -ne $savedExitCode) { $global:LASTEXITCODE = $savedExitValue }
    else { Remove-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue }
}