#Requires -Version 5.1
<#
.SYNOPSIS
    Offline tests for the Blob probe with launcher-level CLI mocks.
.DESCRIPTION
    Intercepts all executable discovery; never invokes Azure CLI, IMDS or Blob.
    Runs the full probe against a batch fixture, including credential cleanup,
    ACLs, limited list arguments, safe diagnostics and error handling.
#>
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Windows is required for these offline tests.' }
$probePath = Join-Path (Split-Path $PSScriptRoot -Parent) 'check-access.ps1'
$fixturePath = Join-Path $PSScriptRoot 'fixtures\az-launcher-mock.cmd'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($probePath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'The Blob probe has PowerShell syntax errors.' }
foreach ($functionName in @('New-BlobListArguments', 'Get-BlobDiagnosticMetadata', 'Get-ProbeCliVersion')) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $functionName
    }, $true)
    if (-not $functionAst) { throw 'A production helper was not found.' }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}
function Assert {
    param([bool]$Condition, [string]$Case)
    if (-not $Condition) { throw "FAIL: $Case" }
    Write-Output "PASS: $Case"
}
function Get-Command {
    param([string]$Name, [string]$CommandType, [string]$ErrorAction)
    if ($Name -ne 'az' -or $CommandType -ne 'Application') { throw 'Unexpected executable lookup.' }
    if (-not $mockState.CliMissing) { [pscustomobject]@{ Source = $fixturePath } }
}
function Set-Acl {
    param([string]$LiteralPath, [System.Security.AccessControl.DirectorySecurity]$AclObject)
    if ($mockState.AclFailure) { throw 'ELV_TEST_PRIVATE_ACL_FAILURE' }
    Microsoft.PowerShell.Security\Set-Acl -LiteralPath $LiteralPath -AclObject $AclObject
    $acl = Get-Acl -LiteralPath $LiteralPath
    if (-not $acl.AreAccessRulesProtected) { throw 'Unprotected ACL.' }
    $allowed = @([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18')
    foreach ($rule in $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])) {
        if ($rule.IdentityReference.Value -notin $allowed) { throw 'Unexpected ACL grantee.' }
    }
    $mockState.AclChecks++
}
function Assert-EnvironmentRestored {
    foreach ($name in $testEnvironment.Keys) {
        if ([Environment]::GetEnvironmentVariable($name, 'Process') -cne $testEnvironment[$name]) { throw "Not restored: $name" }
    }
    Write-Output 'PASS: Complete caller environment restored'
}
function Assert-CacheCleanup {
    foreach ($line in (Get-Content -LiteralPath $env:ELV_BLOB_TEST_LOG | Where-Object { $_ -like 'CACHE|*' })) {
        if (Test-Path -LiteralPath (Split-Path $line.Substring(6) -Parent)) { throw 'A private cache survived the invocation.' }
    }
    Write-Output 'PASS: Private cache and diagnostic files removed'
}

$settings = @{ AccountName = 'elvteststorage'; ContainerName = 'approved-container'; ClientId = '11111111-1111-1111-1111-111111111111' }
$mockState = @{ CliMissing = $false; AclFailure = $false; AclChecks = 0 }
$scratch = Join-Path ([System.IO.Path]::GetTempPath()) ('elv blob test ' + [Guid]::NewGuid().ToString('N'))
$testEnvironment = @{
    AZURE_CONFIG_DIR = (Join-Path $scratch 'caller-cache')
    AZURE_CORE_COLLECT_TELEMETRY = 'true'
    AZURE_EXTENSION_USE_DYNAMIC_INSTALL = 'yes_prompt'
    NO_PROXY = 'corp.example.test'
    AZURE_STORAGE_KEY = 'ELV_TEST_NOT_A_KEY'
    AZURE_STORAGE_SAS_TOKEN = 'ELV_TEST_NOT_A_SAS'
    AZURE_STORAGE_CONNECTION_STRING = 'ELV_TEST_NOT_A_CONNECTION_STRING'
    AZURE_STORAGE_ACCOUNT = 'ELV_TEST_WRONG_ACCOUNT'
    AZURE_STORAGE_ACCOUNT_URL = 'https://unrelated.example.test/'
    AZURE_STORAGE_SERVICE_ENDPOINT = 'https://unrelated.example.test/'
    AZURE_STORAGE_AUTH_MODE = 'key'
    AZURE_CLIENT_SECRET = 'ELV_TEST_NOT_A_SECRET'
    AZURE_CLIENT_CERTIFICATE_PATH = 'ELV_TEST_NOT_A_CERTIFICATE'
    AZURE_FEDERATED_TOKEN_FILE = 'ELV_TEST_NOT_A_TOKEN_FILE'
}
$savedEnvironment = @{}
foreach ($name in (@($testEnvironment.Keys) + @(
    'ELV_BLOB_TEST_LOG', 'ELV_BLOB_TEST_LOGIN_EXIT', 'ELV_BLOB_TEST_LIST_EXIT',
    'ELV_BLOB_TEST_LIST_ERROR', 'ELV_BLOB_TEST_LIST_JSON', 'ELV_BLOB_TEST_HTTP_STATUS',
    'ELV_BLOB_TEST_VERSION_JSON', 'ELV_BLOB_TEST_VERSION_EXIT'
))) { $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$savedExitCode = Get-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
$savedExitValue = if ($null -ne $savedExitCode) { $savedExitCode.Value } else { $null }
try {
    New-Item -ItemType Directory -Path $scratch | Out-Null
    foreach ($name in $testEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $testEnvironment[$name], 'Process') }
    $env:ELV_BLOB_TEST_LOG = Join-Path $scratch 'calls.txt'
    $env:ELV_BLOB_TEST_LOGIN_EXIT = '0'
    $env:ELV_BLOB_TEST_LIST_EXIT = '0'
    $env:ELV_BLOB_TEST_HTTP_STATUS = $null
    $env:ELV_BLOB_TEST_LIST_ERROR = 'ELV_TEST_PRIVATE_DIAGNOSTIC'
    $env:ELV_BLOB_TEST_LIST_JSON = '[{"name":"ELV_TEST_PRIVATE_BLOB"},{"nextMarker":"ELV_TEST_PRIVATE_MARKER"}]'
    $env:ELV_BLOB_TEST_VERSION_JSON = '{"azure-cli":"2.90.0","extensions":{"ELV_TEST_PRIVATE_EXTENSION":"hidden"}}'
    $env:ELV_BLOB_TEST_VERSION_EXIT = '0'

    $expectedList = 'storage blob list --account-name elvteststorage --blob-endpoint https://elvteststorage.blob.core.windows.net/ --container-name approved-container --auth-mode login --num-results 1 --timeout 30 --show-next-marker --output none'
    $arguments = @(New-BlobListArguments -AccountName $settings.AccountName -ContainerName $settings.ContainerName)
    Assert (($arguments -join ' ') -ceq $expectedList) 'Exact account/container/standard endpoint and login-only limited listing'
    Assert ((($arguments -join ' ') -notmatch '[()''"&|<>^%]')) 'Arguments safe for parenthesized Windows CLI launcher'

    foreach ($badAccount in @('', 'ab', ('a' * 25), 'MixedCase', 'account-name', 'https://elvteststorage.blob.core.windows.net', 'name&command', 'name-microsoftrouting')) {
        $bad = $settings.Clone(); $bad.AccountName = $badAccount
        $output = @(& $probePath @bad -ApprovedAzureHost)
        Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'CONFIGURATION_ERROR:*' -and -not (Test-Path $env:ELV_BLOB_TEST_LOG)) 'Invalid account rejected before CLI'
    }
    foreach ($badContainer in @('', 'ab', ('a' * 64), 'MixedCase', 'a--b', 'a_b', '../container', 'container?sig=bad', 'container/other', '-container', 'container-')) {
        $bad = $settings.Clone(); $bad.ContainerName = $badContainer
        $output = @(& $probePath @bad -ApprovedAzureHost)
        Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'CONFIGURATION_ERROR:*' -and -not (Test-Path $env:ELV_BLOB_TEST_LOG)) 'Invalid container rejected before CLI'
    }
    foreach ($badIdentity in @('', 'not-a-uuid', '00000000-0000-0000-0000-000000000000')) {
        $bad = $settings.Clone(); $bad.ClientId = $badIdentity
        $output = @(& $probePath @bad -ApprovedAzureHost)
        Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'CONFIGURATION_ERROR:*' -and -not (Test-Path $env:ELV_BLOB_TEST_LOG)) 'Invalid identity rejected before CLI'
    }
    $output = @(& $probePath @settings -Diagnostics)
    Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'HOST_REQUIRED:*' -and -not (Test-Path $env:ELV_BLOB_TEST_LOG)) 'Host/target approval required before CLI'
    $mockState.CliMissing = $true
    $output = @(& $probePath @settings -ApprovedAzureHost)
    Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'PREREQUISITE_MISSING:*') 'Missing CLI fails closed'
    $mockState.CliMissing = $false
    $mockState.AclFailure = $true
    $output = @(& $probePath @settings -ApprovedAzureHost -Diagnostics)
    Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'PROBE_ERROR:*' -and -not (Test-Path $env:ELV_BLOB_TEST_LOG) -and ($output -join "`n") -notmatch 'ELV_TEST_') 'Failed ACL prevents login and hides local error details'
    Assert-EnvironmentRestored
    $mockState.AclFailure = $false

    $output = @(& $probePath @settings -ApprovedAzureHost)
    Assert ($global:LASTEXITCODE -eq 0 -and $output[0] -like 'BLOB_READ_SUCCEEDED:*') 'Mocked listing succeeds through Windows CLI launcher'
    $calls = @(Get-Content -LiteralPath $env:ELV_BLOB_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
    Assert ($calls.Count -eq 2 -and $calls[0] -ceq 'CALL|login --identity --client-id 11111111-1111-1111-1111-111111111111 --allow-no-subscriptions --output none --only-show-errors' -and $calls[1] -ceq ('CALL|' + $expectedList + ' --only-show-errors')) 'Only explicit MI login and one scoped list invocation; no keys/download/write/fallback'
    Assert (($output -join "`n") -notmatch 'ELV_TEST_|nextMarker|access_token|Bearer') 'Blob names, properties, markers and raw diagnostics suppressed'
    Assert ($mockState.AclChecks -eq 1) 'Private ACL set before mocked login'
    Assert ((Get-Content -LiteralPath $env:ELV_BLOB_TEST_LOG -Raw) -match 'BYPASS\|corp.example.test,169.254.169.254,127.0.0.1,localhost') 'Existing corporate bypass preserved'
    Assert-EnvironmentRestored
    Assert-CacheCleanup

    $env:ELV_BLOB_TEST_LIST_JSON = '[]'
    $output = @(& $probePath @settings -ApprovedAzureHost -Diagnostics)
    Assert ($global:LASTEXITCODE -eq 0 -and $output[0] -like 'BLOB_READ_SUCCEEDED:*' -and ($output -join "`n") -notmatch 'ELV_TEST_|BLOB_DIAGNOSTICS:') 'Empty container and verbose success are valid and private'

    Remove-Item -LiteralPath $env:ELV_BLOB_TEST_LOG
    $env:ELV_BLOB_TEST_LOGIN_EXIT = '7'
    $output = @(& $probePath @settings -ApprovedAzureHost -Diagnostics)
    $calls = @(Get-Content -LiteralPath $env:ELV_BLOB_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
    Assert ($global:LASTEXITCODE -eq 3 -and $output[0] -like 'IDENTITY_LOGIN_FAILED:*' -and $calls.Count -eq 2 -and $calls[1] -ceq 'CALL|version --output json --only-show-errors') 'Failed login prevents listing; diagnostic version cannot overwrite failure'
    Assert (($output -join "`n") -match 'stage=LOGIN; cli_exit=7;' -and ($output -join "`n") -notmatch 'ELV_TEST_') 'Login failure diagnostic redacted'
    Assert-EnvironmentRestored
    Assert-CacheCleanup

    $env:ELV_BLOB_TEST_LOGIN_EXIT = '0'
    $env:ELV_BLOB_TEST_LIST_EXIT = '8'
    foreach ($case in @(
        @{ Detail = 'ErrorCode:AuthorizationPermissionMismatch'; Prefix = 'BLOB_FORBIDDEN:' },
        @{ Detail = 'ErrorCode:AuthorizationFailure'; Prefix = 'BLOB_FORBIDDEN:' },
        @{ Detail = 'ErrorCode:AuthenticationFailed'; Prefix = 'BLOB_AUTHENTICATION_FAILED:' },
        @{ Detail = 'ErrorCode:ContainerNotFound'; Prefix = 'BLOB_NOT_FOUND:' },
        @{ Detail = '429 TooManyRequests'; Prefix = 'BLOB_THROTTLED:' },
        @{ Detail = 'ErrorCode:ServerBusy'; Prefix = 'BLOB_SERVICE_ERROR:' },
        @{ Detail = 'SSL certificate verify failed'; Prefix = 'BLOB_CONNECTIVITY_FAILED:' },
        @{ Detail = 'ErrorCode:InvalidResourceName'; Prefix = 'BLOB_REQUEST_REJECTED:' },
        @{ Detail = 'unrecognized arguments'; Prefix = 'BLOB_CLI_INVOCATION_FAILED:' },
        @{ Detail = 'az was unexpected at this time'; Prefix = 'BLOB_CLI_INVOCATION_FAILED:' },
        @{ Detail = 'TypeError: ELV_TEST_PRIVATE_DETAIL'; Prefix = 'BLOB_CLI_PROCESSING_FAILED:' },
        @{ Detail = 'ELV_TEST_PRIVATE_DETAIL'; Prefix = 'BLOB_READ_FAILED:' }
    )) {
        Remove-Item -LiteralPath $env:ELV_BLOB_TEST_LOG
        $env:ELV_BLOB_TEST_LIST_ERROR = $case.Detail
        $output = @(& $probePath @settings -ApprovedAzureHost)
        Assert ($global:LASTEXITCODE -eq 4 -and $output[0].StartsWith($case.Prefix) -and ($output -join "`n") -notmatch 'ELV_TEST_|BLOB_DIAGNOSTICS:') ('Safe category ' + $case.Prefix)
        $calls = @(Get-Content -LiteralPath $env:ELV_BLOB_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
        Assert ($calls.Count -eq 2) 'No alternate endpoint, credentials or script retry'
        Assert-EnvironmentRestored
        Assert-CacheCleanup
    }

    foreach ($case in @(
        @{ Status = '403'; Detail = 'ErrorCode:AuthorizationPermissionMismatch ELV_TEST_PRIVATE_DETAIL'; Code = 'AuthorizationPermissionMismatch'; Prefix = 'BLOB_FORBIDDEN:' },
        @{ Status = '500'; Detail = 'ELV_TEST_PRIVATE_DETAIL'; Code = 'UNKNOWN'; Prefix = 'BLOB_SERVICE_ERROR:' },
        @{ Status = ''; Detail = 'ELV_TEST_PRIVATE_DETAIL'; Code = 'UNKNOWN'; Prefix = 'BLOB_READ_FAILED:' }
    )) {
        Remove-Item -LiteralPath $env:ELV_BLOB_TEST_LOG
        $env:ELV_BLOB_TEST_HTTP_STATUS = $case.Status
        $env:ELV_BLOB_TEST_LIST_ERROR = $case.Detail
        $output = @(& $probePath @settings -ApprovedAzureHost -Diagnostics)
        $status = if ($case.Status) { $case.Status } else { 'UNKNOWN' }
        $expected = 'BLOB_DIAGNOSTICS: stage=LIST; cli_exit=8; http_status={0}; storage_error={1}; error_kind=NONE_RECOGNIZED; cli_version=2.90.0' -f $status, $case.Code
        Assert ($global:LASTEXITCODE -eq 4 -and $output[0].StartsWith($case.Prefix) -and $output -contains $expected) 'Diagnostic status/code/version are safe and do not mask list failure'
        Assert (($output -join "`n") -notmatch 'ELV_TEST_|extensions|nextMarker') 'Verbose logs and CLI extras never leak'
        $calls = @(Get-Content -LiteralPath $env:ELV_BLOB_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
        Assert ($calls.Count -eq 3 -and $calls[1] -ceq ('CALL|' + $expectedList + ' --verbose') -and $calls[2] -ceq 'CALL|version --output json --only-show-errors') 'One list plus local version in diagnostic mode; no debug'
        Assert-EnvironmentRestored
        Assert-CacheCleanup
    }
    $metadata = Get-BlobDiagnosticMetadata -Detail "INFO: Response status: 301`nINFO: Response status: 403`nELV_TEST_PRIVATE_DETAIL"
    Assert ($metadata.HttpStatus -eq '403' -and $metadata.StorageCode -eq 'UNKNOWN') 'Final explicit response status, not arbitrary detail'
    $metadata = Get-BlobDiagnosticMetadata -Detail 'Response status: ELV_TEST_PRIVATE_STATUS; ErrorCode:ELV_TEST_PRIVATE_CODE'
    Assert ($metadata.HttpStatus -eq 'UNKNOWN' -and $metadata.StorageCode -eq 'UNKNOWN') 'Unrecognized status/error values never echoed'
    $metadata = Get-BlobDiagnosticMetadata -Detail ''
    Assert ($metadata.HttpStatus -eq 'UNKNOWN' -and $metadata.ErrorKind -eq 'EMPTY_DIAGNOSTICS') 'Empty errors explicitly unknown'
    $env:ELV_BLOB_TEST_VERSION_JSON = '{"azure-cli":"ELV_TEST_PRIVATE_VERSION"}'
    $output = @(& $probePath @settings -ApprovedAzureHost -Diagnostics)
    Assert ($global:LASTEXITCODE -eq 4 -and ($output -join "`n") -match 'cli_version=UNKNOWN' -and ($output -join "`n") -notmatch 'ELV_TEST_') 'Malformed version cannot expose raw values'
    $env:ELV_BLOB_TEST_VERSION_EXIT = '9'
    $output = @(& $probePath @settings -ApprovedAzureHost -Diagnostics)
    Assert ($global:LASTEXITCODE -eq 4 -and ($output -join "`n") -match 'cli_exit=8;.*cli_version=UNKNOWN') 'Failed version lookup preserves original operation exit'
    Assert-EnvironmentRestored
    Assert-CacheCleanup
}
finally {
    foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force }
    if ($null -ne $savedExitCode) { $global:LASTEXITCODE = $savedExitValue }
    else { Remove-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue }
}