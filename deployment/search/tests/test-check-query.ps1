#Requires -Version 5.1
<#
.SYNOPSIS
    Offline Search probe tests with no Azure CLI, IMDS or document requests.
.DESCRIPTION
    Loads the URL helper and intercepts Get-Command in test scope to substitute
    only a harmless local batch launcher and command fixture. Exercises the
    complete probe's gates, secure cache, shell parsing, native arguments,
    sanitized outputs and cleanup paths.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'These offline tests require Windows.'
}
$probePath = Join-Path (Split-Path $PSScriptRoot -Parent) 'check-query.ps1'
$fixturePath = Join-Path $PSScriptRoot 'fixtures\az-launcher-mock.cmd'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $probePath, [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) { throw 'The Search probe has syntax errors.' }
foreach ($functionName in @('New-SearchCountUrl', 'New-SearchProbeRequest', 'Test-EmptySearchResponse', 'Invoke-ProbeAz', 'Get-SearchDiagnosticMetadata', 'Get-ProbeCliVersion')) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if (-not $functionAst) { throw 'A production helper was not found.' }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

function Assert {
    param([bool]$Condition, [string]$Case)
    if (-not $Condition) { throw "FAIL: $Case" }
    Write-Output "PASS: $Case"
}

function Normalize-RequestLine {
    param([string]$Line)
    return $Line -replace ' --headers x-ms-client-request-id=[0-9a-f-]{36}', ''
}

function Get-Command {
    param([string]$Name, [string]$CommandType, [string]$ErrorAction)
    if ($Name -ne 'az' -or $CommandType -ne 'Application') {
        throw 'Unexpected executable lookup in offline test.'
    }
    if (-not $mockState.CliMissing) { [pscustomobject]@{ Source = $fixturePath } }
}

function Assert-PrivateCache {
    param([string]$Path)
    $parent = Split-Path $Path -Parent
    $acl = Get-Acl -LiteralPath $parent
    if (-not $acl.AreAccessRulesProtected) { throw 'Cache ACL is not protected.' }
    $allowed = @([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18')
    foreach ($rule in $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])) {
        if ($rule.IdentityReference.Value -notin $allowed) { throw 'Cache has unexpected access.' }
    }
}

# Observe the ACL during production setup before mocked native invocations. No test path
# can resolve real Azure CLI. This is a test-only wrapper, not a probe hook.
function Set-Acl {
    param([string]$LiteralPath, [System.Security.AccessControl.DirectorySecurity]$AclObject)
    Microsoft.PowerShell.Security\Set-Acl -LiteralPath $LiteralPath -AclObject $AclObject
    Assert-PrivateCache -Path (Join-Path $LiteralPath 'azure')
    $mockState.AclChecks++
}

function Assert-EnvironmentRestored {
    foreach ($name in $testEnvironment.Keys) {
        if ([Environment]::GetEnvironmentVariable($name, 'Process') -cne $testEnvironment[$name]) {
            throw "Environment not restored: $name"
        }
    }
    Write-Output 'PASS: Complete caller environment restored'
}

function Assert-CacheCleanup {
    foreach ($line in (Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG | Where-Object { $_ -like 'CACHE|*' })) {
        if (Test-Path -LiteralPath (Split-Path $line.Substring(6) -Parent)) {
            throw 'Private probe directory survived the invocation.'
        }
    }
    Write-Output 'PASS: Private probe files removed'
}

$settings = @{
    Endpoint = 'https://elv-test.search.windows.net/'
    IndexName = 'test-index'
    ClientId = '11111111-1111-1111-1111-111111111111'
}
# A shared object avoids script-scope rebinding when mocks run from the probe.
$mockState = @{ CliMissing = $false; AclChecks = 0 }
$scratch = Join-Path ([System.IO.Path]::GetTempPath()) ('elv search test ' + [Guid]::NewGuid().ToString('N'))
$testEnvironment = @{
    AZURE_CONFIG_DIR = (Join-Path $scratch 'caller-cache')
    AZURE_CORE_COLLECT_TELEMETRY = 'true'
    NO_PROXY = 'corp.example.test'
    AZURE_CLIENT_SECRET = 'ELV_TEST_NOT_A_SECRET'
    AZURE_CLIENT_CERTIFICATE_PATH = 'ELV_TEST_NOT_A_CERTIFICATE'
    AZURE_FEDERATED_TOKEN_FILE = 'ELV_TEST_NOT_A_TOKEN_FILE'
    AZURE_SEARCH_API_KEY = 'ELV_TEST_NOT_AN_API_KEY'
    AZURE_SEARCH_KEY = 'ELV_TEST_NOT_A_KEY'
}
$savedEnvironment = @{}
foreach ($name in (@($testEnvironment.Keys) + @(
    'ELV_SEARCH_TEST_LOG', 'ELV_SEARCH_TEST_LOGIN_EXIT',
    'ELV_SEARCH_TEST_REST_EXIT', 'ELV_SEARCH_TEST_REST_ERROR', 'ELV_SEARCH_TEST_COUNT',
    'ELV_SEARCH_TEST_HTTP_STATUS', 'ELV_SEARCH_TEST_QUERY_RESPONSE', 'ELV_SEARCH_TEST_RESPONSE_HEADERS'
))) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$savedExitCode = Get-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
$savedExitValue = if ($null -ne $savedExitCode) { $savedExitCode.Value } else { $null }
try {
    New-Item -ItemType Directory -Path $scratch | Out-Null
    foreach ($name in $testEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $testEnvironment[$name], 'Process')
    }
    $env:ELV_SEARCH_TEST_LOG = Join-Path $scratch 'calls.txt'
    $env:ELV_SEARCH_TEST_LOGIN_EXIT = '0'
    $env:ELV_SEARCH_TEST_REST_EXIT = '0'
    $env:ELV_SEARCH_TEST_REST_ERROR = 'ELV_TEST_RAW_DIAGNOSTIC'
    $env:ELV_SEARCH_TEST_COUNT = '123456789'
    $env:ELV_SEARCH_TEST_HTTP_STATUS = $null
    $env:ELV_SEARCH_TEST_QUERY_RESPONSE = '{"value":[]}'
    $env:ELV_SEARCH_TEST_RESPONSE_HEADERS = $null

    # Replay the former URL through a launcher with a parenthesized IF block,
    # not directly through the handler (which missed the real parsing failure).
    $legacyUrl = "https://elv-test.search.windows.net/indexes('test-index')" + '/docs/$count?api-version=2026-04-01'
    $legacyErrorFile = Join-Path $scratch 'legacy-shell-error.txt'
    $azCommand = [pscustomobject]@{ Source = $fixturePath }
    $legacyCode = Invoke-ProbeAz -Arguments @(
        'rest', '--method', 'get', '--url', $legacyUrl,
        '--resource', 'https://search.azure.com', '--output', 'none', '--only-show-errors'
    ) -ErrorFile $legacyErrorFile
    Assert ($legacyCode -eq 255 -and -not (Test-Path $env:ELV_SEARCH_TEST_LOG)) 'Former URL reproduces shell exit 255 before handler execution'
    Assert-EnvironmentRestored

    $expectedUrl = 'https://elv-test.search.windows.net/indexes/test-index/docs/$count?api-version=2026-04-01'
    $url = New-SearchCountUrl -Endpoint $settings.Endpoint -IndexName $settings.IndexName
    Assert ($url -ceq $expectedUrl) 'Exact document-count route with literal dollar sign'
    Assert ($url -notmatch '[()''"&|<>^%\s]') 'Count URL contains no batch command metacharacters'
    Assert ((New-SearchCountUrl -Endpoint $settings.Endpoint.TrimEnd('/') -IndexName $settings.IndexName) -ceq $expectedUrl) 'Optional trailing slash normalized'

    foreach ($badEndpoint in @(
        '', 'http://elv-test.search.windows.net', 'https://example.com',
        'https://elv-test.search.windows.net.evil.example',
        'https://elv-test.search.windows.net/indexes',
        'https://user:password@elv-test.search.windows.net',
        'https://elv-test.search.windows.net?key=bad',
        'https://elv-test.search.windows.net:8443'
    )) {
        $bad = $settings.Clone()
        $bad.Endpoint = $badEndpoint
        $output = @(& $probePath @bad -ApprovedAzureHost)
        Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'CONFIGURATION_ERROR:*' -and -not (Test-Path $env:ELV_SEARCH_TEST_LOG)) 'Unsafe endpoint rejected before CLI'
    }
    foreach ($badIndex in @('', 'a', 'BadIndex', '../index', "test')/docs", 'test?x=y', 'test&other', 'test--index', ('a' * 129))) {
        $bad = $settings.Clone()
        $bad.IndexName = $badIndex
        $output = @(& $probePath @bad -ApprovedAzureHost)
        Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'CONFIGURATION_ERROR:*' -and -not (Test-Path $env:ELV_SEARCH_TEST_LOG)) 'Unsafe index rejected before CLI'
    }
    foreach ($badClientId in @('', 'not-a-uuid', '00000000-0000-0000-0000-000000000000')) {
        $bad = $settings.Clone()
        $bad.ClientId = $badClientId
        $output = @(& $probePath @bad -ApprovedAzureHost)
        Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'CONFIGURATION_ERROR:*' -and -not (Test-Path $env:ELV_SEARCH_TEST_LOG)) 'Invalid identity rejected before CLI'
    }
    $output = @(& $probePath @settings)
    Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'HOST_REQUIRED:*' -and -not (Test-Path $env:ELV_SEARCH_TEST_LOG)) 'Host and target approval required before CLI'
    $mockState.CliMissing = $true
    $output = @(& $probePath @settings -ApprovedAzureHost)
    Assert ($global:LASTEXITCODE -eq 2 -and $output[0] -like 'PREREQUISITE_MISSING:*' -and -not (Test-Path $env:ELV_SEARCH_TEST_LOG)) 'Missing CLI fails before authentication'
    $mockState.CliMissing = $false

    $output = @(& $probePath @settings -ApprovedAzureHost)
    Assert ($global:LASTEXITCODE -eq 0 -and $output[0] -like 'SEARCH_READ_SUCCEEDED:*') 'Mocked login and count succeed'
    $calls = @(Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
    Assert ($calls.Count -eq 2 -and $calls[0] -ceq 'CALL|login --identity --client-id 11111111-1111-1111-1111-111111111111 --allow-no-subscriptions --output none --only-show-errors') 'Only explicit managed-identity login'
    Assert ($calls[1] -ceq ('CALL|rest --method get --url ' + $expectedUrl + ' --resource https://search.azure.com --output none --only-show-errors')) 'Only GET count with Search audience; no query/list/write/body/key'
    Assert (($output -join "`n") -notmatch '123456789|ELV_TEST_|access_token|Bearer') 'Count and raw diagnostics suppressed'
    $log = Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG -Raw
    Assert ($log -match 'BYPASS\|corp.example.test,169.254.169.254,127.0.0.1,localhost') 'Corporate proxy bypasses preserved'
    Assert ($mockState.AclChecks -eq 1) 'Private ACL verified before mock login'
    Assert-EnvironmentRestored
    Assert-CacheCleanup

    $env:ELV_SEARCH_TEST_COUNT = '0'
    $output = @(& $probePath @settings -ApprovedAzureHost)
    Assert ($global:LASTEXITCODE -eq 0 -and $output[0] -like 'SEARCH_READ_SUCCEEDED:*') 'Empty index is a successful count'

    Remove-Item -LiteralPath $env:ELV_SEARCH_TEST_LOG
    $env:ELV_SEARCH_TEST_LOGIN_EXIT = '7'
    $output = @(& $probePath @settings -ApprovedAzureHost)
    $calls = @(Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
    Assert ($global:LASTEXITCODE -eq 3 -and $output[0] -like 'IDENTITY_LOGIN_FAILED:*' -and $calls.Count -eq 1) 'Failed login prevents Search request'
    Assert-EnvironmentRestored
    Assert-CacheCleanup

    $env:ELV_SEARCH_TEST_LOGIN_EXIT = '0'
    $env:ELV_SEARCH_TEST_REST_EXIT = '8'
    foreach ($case in @(
        @{ Detail = '403 Forbidden ELV_TEST_RAW_DIAGNOSTIC'; Prefix = 'SEARCH_FORBIDDEN:' },
        @{ Detail = '401 Unauthorized'; Prefix = 'SEARCH_AUTHENTICATION_FAILED:' },
        @{ Detail = '404 IndexNotFound'; Prefix = 'SEARCH_NOT_FOUND:' },
        @{ Detail = '429 TooManyRequests'; Prefix = 'SEARCH_THROTTLED:' },
        @{ Detail = 'SSL certificate verify failed'; Prefix = 'SEARCH_CONNECTIVITY_FAILED:' },
        @{ Detail = '400 Bad Request'; Prefix = 'SEARCH_REQUEST_REJECTED:' },
        @{ Detail = 'BadRequest'; Prefix = 'SEARCH_REQUEST_REJECTED:' },
        @{ Detail = 'ServiceUnavailable'; Prefix = 'SEARCH_SERVICE_ERROR:' },
        @{ Detail = "TypeError: 'int' object is not iterable"; Prefix = 'SEARCH_CLI_PROCESSING_FAILED:' },
        @{ Detail = 'az was unexpected at this time'; Prefix = 'SEARCH_CLI_INVOCATION_FAILED:' },
        @{ Detail = 'ELV_TEST_RAW_DIAGNOSTIC'; Prefix = 'SEARCH_READ_FAILED:' }
    )) {
        Remove-Item -LiteralPath $env:ELV_SEARCH_TEST_LOG
        $env:ELV_SEARCH_TEST_REST_ERROR = $case.Detail
        $output = @(& $probePath @settings -ApprovedAzureHost)
        Assert ($global:LASTEXITCODE -eq 4 -and $output[0].StartsWith($case.Prefix) -and ($output -join "`n") -notmatch 'ELV_TEST_') ('Sanitized failure ' + $case.Prefix)
        $calls = @(Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
        Assert ($calls.Count -eq 2) 'No retries or broader access after failure'
        Assert (($output -join "`n") -notmatch 'SEARCH_DIAGNOSTICS:') 'Diagnostic mode is opt-in'
        Assert-EnvironmentRestored
        Assert-CacheCleanup
    }

    foreach ($case in @(
        @{ Status = '200'; Detail = "TypeError: 'int' object is not iterable ELV_TEST_PRIVATE_VALUE"; Kind = 'CLI_SCALAR_RESPONSE'; Prefix = 'SEARCH_CLI_PROCESSING_FAILED:' },
        @{ Status = '403'; Detail = 'ELV_TEST_PRIVATE_VALUE'; Kind = 'NONE_RECOGNIZED'; Prefix = 'SEARCH_FORBIDDEN:' },
        @{ Status = '503'; Detail = 'ELV_TEST_PRIVATE_VALUE'; Kind = 'NONE_RECOGNIZED'; Prefix = 'SEARCH_SERVICE_ERROR:' },
        @{ Status = ''; Detail = 'ELV_TEST_PRIVATE_VALUE'; Kind = 'NONE_RECOGNIZED'; Prefix = 'SEARCH_READ_FAILED:' }
    )) {
        Remove-Item -LiteralPath $env:ELV_SEARCH_TEST_LOG
        $env:ELV_SEARCH_TEST_HTTP_STATUS = $case.Status
        $env:ELV_SEARCH_TEST_REST_ERROR = $case.Detail
        $output = @(& $probePath @settings -ApprovedAzureHost -Diagnostics)
        $expectedStatus = if ($case.Status) { $case.Status } else { 'UNKNOWN' }
        $expectedDiagnostic = 'SEARCH_DIAGNOSTICS: cli_exit=8; http_status={0}; error_kind={1}; cli_version=2.80.0' -f $expectedStatus, $case.Kind
        Assert ($global:LASTEXITCODE -eq 4 -and @($output | Where-Object { $_.StartsWith($case.Prefix) }).Count -eq 1 -and $output -contains $expectedDiagnostic) 'Safe diagnostic metadata and failure exit preserved'
        Assert (($output -join "`n") -notmatch 'ELV_TEST_|123456789|extensions|TypeError:') 'No private diagnostics, count or version extras leak'
        $calls = @(Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
        Assert ($calls.Count -eq 3 -and (Normalize-RequestLine $calls[1]) -ceq ('CALL|rest --method get --url ' + $expectedUrl + ' --resource https://search.azure.com --output none --verbose') -and $calls[2] -ceq 'CALL|version --output json --only-show-errors') 'One count request plus local version check; no debug or retries'
        Assert (($output -join "`n") -match 'SEARCH_REQUEST: operation=Count; api_version=2026-04-01; utc=[0-9TZ:.-]+; client_request_id=[0-9a-f-]{36};') 'Client correlation and UTC available for support'
        Assert-EnvironmentRestored
        Assert-CacheCleanup
    }

    $metadata = Get-SearchDiagnosticMetadata -Detail "INFO: Response status: 301`nINFO: Response status: 200`nAuthorization: ELV_TEST_PRIVATE_VALUE 403`n123456789"
    Assert ($metadata.HttpStatus -eq '200' -and $metadata.ErrorKind -eq 'NONE_RECOGNIZED') 'Final explicit response status used, not unrelated numbers'
    $metadata = Get-SearchDiagnosticMetadata -Detail ''
    Assert ($metadata.HttpStatus -eq 'UNKNOWN' -and $metadata.ErrorKind -eq 'EMPTY_DIAGNOSTICS') 'Empty diagnostics remain explicitly unknown'
    $metadata = Get-SearchDiagnosticMetadata -Detail 'INFO: Response status: ELV_TEST_PRIVATE_VALUE'
    Assert ($metadata.HttpStatus -eq 'UNKNOWN') 'Non-numeric response status never echoed'
    foreach ($case in @(
        @{ Detail = 'JSONDecodeError: ELV_TEST_PRIVATE_VALUE'; Kind = 'CLI_JSON_PROCESSING' },
        @{ Detail = 'AttributeError: ELV_TEST_PRIVATE_VALUE'; Kind = 'CLI_RESPONSE_PROCESSING' },
        @{ Detail = 'unrecognized arguments ELV_TEST_PRIVATE_VALUE'; Kind = 'CLI_ARGUMENTS' }
    )) {
        $metadata = Get-SearchDiagnosticMetadata -Detail $case.Detail
        Assert ($metadata.ErrorKind -eq $case.Kind) 'Exception details reduced to fixed categories'
    }
    $badVersionFile = Join-Path $scratch 'invalid-version.json'
    [System.IO.File]::WriteAllText($badVersionFile, '{"azure-cli":"ELV_TEST_PRIVATE_VALUE"}')
    Assert ((Get-ProbeCliVersion -OutputFile $badVersionFile) -eq 'UNKNOWN') 'Non-version CLI output never displayed'

    # Diagnostic mode changes logging only: successful counts still need no
    # version invocation and do not expose the response even with verbose logs.
    Remove-Item -LiteralPath $env:ELV_SEARCH_TEST_LOG
    $env:ELV_SEARCH_TEST_REST_EXIT = '0'
    $env:ELV_SEARCH_TEST_HTTP_STATUS = '200'
    $env:ELV_SEARCH_TEST_REST_ERROR = 'ELV_TEST_PRIVATE_VALUE'
    $output = @(& $probePath @settings -ApprovedAzureHost -Diagnostics)
    $calls = @(Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
    Assert ($global:LASTEXITCODE -eq 0 -and @($output | Where-Object { $_ -like 'SEARCH_READ_SUCCEEDED:*' }).Count -eq 1 -and $calls.Count -eq 2 -and ($output -join "`n") -notmatch 'ELV_TEST_|Response status:') 'Verbose success remains private without an extra request'
    Assert-EnvironmentRestored
    Assert-CacheCleanup

    # Fixed top=0 request never requests content, vectors, facets or ACL bypass.
    foreach ($version in @('2026-04-01', '2024-07-01')) {
        $request = New-SearchProbeRequest -Endpoint $settings.Endpoint -IndexName $settings.IndexName -Operation Query -ApiVersion $version
        Assert ($request.Method -ceq 'post' -and $request.Url -ceq ('https://elv-test.search.windows.net/indexes/test-index/docs/search?api-version=' + $version) -and $request.Body -ceq '{"search":"*","queryType":"simple","top":0,"count":false}') 'Explicit API selection and immutable zero-result query'
        Remove-Item -LiteralPath $env:ELV_SEARCH_TEST_LOG
        $output = @(& $probePath @settings -ApprovedAzureHost -Diagnostics -Operation Query -ApiVersion $version)
        Assert ($global:LASTEXITCODE -eq 0 -and @($output | Where-Object { $_ -like 'SEARCH_QUERY_SUCCEEDED:*' }).Count -eq 1) 'Zero-result query succeeds through Windows launcher'
        $calls = @(Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
        Assert ($calls.Count -eq 2 -and $calls[1].Contains($request.Url) -and $calls[1] -match '--body @.+ --output-file .+ --headers Content-Type=application/json x-ms-client-request-id=[0-9a-f-]{36} --verbose$') 'One query with private request/response files and correlation header'
        Assert ((Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG -Raw).Contains($request.Body)) 'Exact top=0 payload reached mock'
        Assert-EnvironmentRestored
        Assert-CacheCleanup
    }
    Remove-Item -LiteralPath $env:ELV_SEARCH_TEST_LOG
    $output = @(& $probePath @settings -ApprovedAzureHost -ApiVersion '2024-07-01')
    $calls = @(Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
    Assert ($global:LASTEXITCODE -eq 0 -and $calls[1].Contains('/docs/$count?api-version=2024-07-01')) 'Count API comparison changes only requested version'

    foreach ($body in @('{"value":[{"content":"ELV_TEST_PRIVATE_DOCUMENT"}]}', '{"value":[],"error":{"code":"PartialError"}}', '{}', '[]', 'null', 'ELV_TEST_INVALID_JSON')) {
        $env:ELV_SEARCH_TEST_QUERY_RESPONSE = $body
        $output = @(& $probePath @settings -ApprovedAzureHost -Operation Query)
        Assert ($global:LASTEXITCODE -eq 4 -and $output[0] -like 'SEARCH_RESPONSE_UNEXPECTED:*' -and ($output -join "`n") -notmatch 'ELV_TEST_|PartialError') 'Malformed, partial and nonempty responses fail closed without exposure'
    }
    $env:ELV_SEARCH_TEST_QUERY_RESPONSE = '{"value":[]}'
    $env:ELV_SEARCH_TEST_HTTP_STATUS = '206'
    $output = @(& $probePath @settings -ApprovedAzureHost -Diagnostics -Operation Query)
    Assert ($global:LASTEXITCODE -eq 4 -and @($output | Where-Object { $_ -like 'SEARCH_RESPONSE_UNEXPECTED:*' }).Count -eq 1) 'Observed partial HTTP response is not a passed query'
    Assert-CacheCleanup

    $headersFile = Join-Path $scratch 'response-headers.txt'
    [System.IO.File]::WriteAllText($headersFile, "INFO: Response headers:`nINFO:     'request-id': '22222222-2222-2222-2222-222222222222'`nINFO:     'content-type': 'application/json; charset=utf-8'`nINFO: Response content:`nELV_TEST_PRIVATE_RESPONSE_BODY")
    $env:ELV_SEARCH_TEST_RESPONSE_HEADERS = $headersFile
    $env:ELV_SEARCH_TEST_HTTP_STATUS = '500'
    $env:ELV_SEARCH_TEST_REST_EXIT = '1'
    $output = @(& $probePath @settings -ApprovedAzureHost -Diagnostics -Operation Query)
    Assert ($global:LASTEXITCODE -eq 4 -and ($output -join "`n") -match 'service_request_id=22222222-2222-2222-2222-222222222222; response_type=application/json; http_status=500' -and ($output -join "`n") -notmatch 'ELV_TEST_') 'Server correlation ID and response type extracted without body disclosure'
    $metadata = Get-SearchDiagnosticMetadata -Detail "Response headers:`n    'request-id': 'ELV_TEST_PRIVATE_ID'`n    'content-type': 'ELV_TEST_PRIVATE_TYPE'`nResponse content:`n'request-id': '22222222-2222-2222-2222-222222222222'"
    Assert ($metadata.RequestId -eq 'UNKNOWN' -and $metadata.ContentType -eq 'UNKNOWN') 'Untrusted header values and body impersonation cannot leak'
    Assert-EnvironmentRestored
    Assert-CacheCleanup

    $runnerPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'diagnose-access.ps1'
    $env:ELV_SEARCH_TEST_REST_EXIT = '0'
    $env:ELV_SEARCH_TEST_HTTP_STATUS = '200'
    $env:ELV_SEARCH_TEST_RESPONSE_HEADERS = $null
    Remove-Item -LiteralPath $env:ELV_SEARCH_TEST_LOG
    $output = @(& $runnerPath @settings)
    Assert ($global:LASTEXITCODE -eq 2 -and -not (Test-Path $env:ELV_SEARCH_TEST_LOG)) 'Comparison runner refuses missing host approval'
    $output = @(& $runnerPath @settings -ApprovedAzureHost -ComparisonIndexName 'invalid/index')
    Assert ($global:LASTEXITCODE -eq 2 -and -not (Test-Path $env:ELV_SEARCH_TEST_LOG)) 'All comparison indexes validated before first CLI call'

    # Model an incomplete customer copy in a separate directory (including
    # spaces). The production companion is never changed. These test companions
    # throw if executed; compatibility checks must parse only, before any case.
    $companionDirectory = Join-Path $scratch 'companion checks'
    New-Item -ItemType Directory -Path $companionDirectory | Out-Null
    $isolatedRunnerPath = Join-Path $companionDirectory 'diagnose-access.ps1'
    $isolatedProbePath = Join-Path $companionDirectory 'check-query.ps1'
    Copy-Item -LiteralPath $runnerPath -Destination $isolatedRunnerPath
    $aclChecksBeforeCompatibility = $mockState.AclChecks
    $output = @(& $isolatedRunnerPath @settings -ApprovedAzureHost)
    Assert ($global:LASTEXITCODE -eq 2 -and $output.Count -eq 1 -and $output[0] -like 'PREREQUISITE_MISSING:*' -and -not (Test-Path $env:ELV_SEARCH_TEST_LOG)) 'Missing companion stops before any comparison or CLI'

    $parameterDeclarations = @(
        '[string]$Endpoint', '[string]$IndexName', '[string]$ClientId',
        '[switch]$ApprovedAzureHost', '[switch]$Diagnostics',
        '[string]$Operation', '[string]$ApiVersion'
    )
    foreach ($missingParameter in $parameterDeclarations) {
        $remainingParameters = @($parameterDeclarations | Where-Object { $_ -cne $missingParameter })
        $companionText = "[CmdletBinding()]`nparam(" + ($remainingParameters -join ',') + ")`nthrow 'ELV_TEST_COMPANION_EXECUTED'"
        [System.IO.File]::WriteAllText($isolatedProbePath, $companionText)
        $output = @(& $isolatedRunnerPath @settings -ApprovedAzureHost)
        Assert ($global:LASTEXITCODE -eq 2 -and $output.Count -eq 1 -and $output[0] -like 'PROBE_VERSION_MISMATCH:*' -and -not (Test-Path $env:ELV_SEARCH_TEST_LOG)) ('Incomplete companion rejected without execution: ' + $missingParameter)
    }
    foreach ($companionText in @(
        "[CmdletBinding()]`nparam(",
        "throw 'ELV_TEST_COMPANION_EXECUTED'",
        ('function Nested-Probe { param(' + ($parameterDeclarations -join ',') + ") }`nthrow 'ELV_TEST_COMPANION_EXECUTED'")
    )) {
        [System.IO.File]::WriteAllText($isolatedProbePath, $companionText)
        $output = @(& $isolatedRunnerPath @settings -ApprovedAzureHost)
        Assert ($global:LASTEXITCODE -eq 2 -and $output.Count -eq 1 -and $output[0] -like 'PROBE_VERSION_MISMATCH:*' -and -not (Test-Path $env:ELV_SEARCH_TEST_LOG)) 'Malformed or absent top-level companion signature rejected without execution'
    }
    Assert ($mockState.AclChecks -eq $aclChecksBeforeCompatibility) 'Compatibility failures never create an authentication cache'
    Assert-EnvironmentRestored

    $output = @(& $runnerPath @settings -ApprovedAzureHost)
    $cases = @($output | Where-Object { $_ -like 'SEARCH_CASE:*' })
    $calls = @(Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
    Assert ($global:LASTEXITCODE -eq 0 -and $cases.Count -eq 2 -and $calls.Count -eq 4) 'Default comparison is exactly count and zero-result query'
    Assert-EnvironmentRestored
    Assert-CacheCleanup

    Remove-Item -LiteralPath $env:ELV_SEARCH_TEST_LOG
    $output = @(& $runnerPath @settings -ApprovedAzureHost -ComparisonIndexName 'second-index' -CompareApiVersions)
    $cases = @($output | Where-Object { $_ -like 'SEARCH_CASE:*' })
    $calls = @(Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
    Assert ($global:LASTEXITCODE -eq 0 -and $cases.Count -eq 8 -and $calls.Count -eq 16 -and ($cases -join "`n") -match 'api_version=2024-07-01') 'Explicit two-index two-version matrix is bounded to eight probes'
    Assert-CacheCleanup

    Remove-Item -LiteralPath $env:ELV_SEARCH_TEST_LOG
    $env:ELV_SEARCH_TEST_QUERY_RESPONSE = '{}'
    $output = @(& $runnerPath @settings -ApprovedAzureHost)
    Assert ($global:LASTEXITCODE -eq 4 -and @($output | Where-Object { $_ -like 'SEARCH_READ_SUCCEEDED:*' }).Count -eq 1 -and $output[-1] -like '*at least one check failed*') 'Runner preserves failure when count passes but query fails'
    Assert-CacheCleanup

    Remove-Item -LiteralPath $env:ELV_SEARCH_TEST_LOG
    $env:ELV_SEARCH_TEST_LOGIN_EXIT = '7'
    $output = @(& $runnerPath @settings -ApprovedAzureHost -ComparisonIndexName 'second-index' -CompareApiVersions)
    $calls = @(Get-Content -LiteralPath $env:ELV_SEARCH_TEST_LOG | Where-Object { $_ -like 'CALL|*' })
    Assert ($global:LASTEXITCODE -eq 3 -and $calls.Count -eq 1 -and @($output | Where-Object { $_ -like 'SEARCH_CASE:*' }).Count -eq 1) 'Runner stops immediately on authentication failure'
    Assert-EnvironmentRestored
    Assert-CacheCleanup
}
finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
    if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force }
    if ($null -ne $savedExitCode) { $global:LASTEXITCODE = $savedExitValue }
    else { Remove-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue }
}