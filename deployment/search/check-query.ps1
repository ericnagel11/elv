#Requires -Version 5.1
<#
.SYNOPSIS
    Read-only Azure AI Search count or zero-result query probe for a Windows VM.
.DESCRIPTION
    Uses an explicitly selected VM-attached user-assigned managed identity and
    a private temporary Azure CLI cache. Makes one GET document-count request
    or POST query with top=0 to the approved index. Does not request document content, list
    indexes, inspect schemas, query vectors, invoke models, or change resources.
    Tokens, the count and raw diagnostics are not displayed. Requires Azure CLI,
    not Python or the PoCs. Run with &, never dot-source, and follow approved
    script-signing policy. Use only on the authorized customer Azure Windows VM.
#>
[CmdletBinding()]
param(
    [string]$Endpoint,
    [string]$IndexName,
    [string]$ClientId,
    [switch]$ApprovedAzureHost,
    [switch]$Diagnostics,
    [ValidateSet('Count', 'Query')][string]$Operation = 'Count',
    [ValidateSet('2026-04-01', '2024-07-01')][string]$ApiVersion = '2026-04-01'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function New-SearchCountUrl {
    param(
        [string]$Endpoint, [string]$IndexName,
        [ValidateSet('2026-04-01', '2024-07-01')][string]$ApiVersion = '2026-04-01'
    )
    # Restrict the token destination to commercial Azure AI Search. Private DNS
    # should resolve the normal service hostname; never accept arbitrary URLs.
    if ($Endpoint -cnotmatch '\Ahttps://[a-z0-9][a-z0-9-]*\.search\.windows\.net/?\z') {
        throw 'Provide the approved HTTPS Search service endpoint without a path or credentials.'
    }
    if ($IndexName -cnotmatch '\A[a-z0-9][a-z0-9_-]{0,126}[a-z0-9]\z' -or
        $IndexName.Contains('--')) {
        throw 'Provide a valid 2-128 character lowercase index name, not a URL, path or query.'
    }
    # Use the key-as-segment route: unquoted parentheses in indexes('name')
    # break Windows az.cmd launchers that forward arguments inside IF blocks.
    # Single-quoted suffix preserves literal $count under PowerShell strict mode.
    return $Endpoint.TrimEnd('/') + '/indexes/' + $IndexName +
        '/docs/$count?api-version=' + $ApiVersion
}

function New-SearchProbeRequest {
    param(
        [string]$Endpoint, [string]$IndexName,
        [ValidateSet('Count', 'Query')][string]$Operation,
        [ValidateSet('2026-04-01', '2024-07-01')][string]$ApiVersion
    )
    $url = New-SearchCountUrl -Endpoint $Endpoint -IndexName $IndexName -ApiVersion $ApiVersion
    if ($Operation -eq 'Count') {
        return [pscustomobject]@{ Url = $url; Method = 'get'; Body = $null }
    }
    # The POST is a read-only query, not indexing. No document payloads, facets,
    # count, semantic ranker, vectors, embeddings or ACL bypass headers requested.
    [pscustomobject]@{
        Url = $Endpoint.TrimEnd('/') + '/indexes/' + $IndexName + '/docs/search?api-version=' + $ApiVersion
        Method = 'post'
        Body = '{"search":"*","queryType":"simple","top":0,"count":false}'
    }
}

function Test-EmptySearchResponse {
    param([string]$OutputFile)
    try {
        if ((Get-Item -LiteralPath $OutputFile -ErrorAction Stop).Length -gt 65536) { return $false }
        $response = Get-Content -LiteralPath $OutputFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $response -or $response -is [array]) { return $false }
        $errorProperty = $response.PSObject.Properties['error']
        if ($null -ne $errorProperty) { return $false }
        $valueProperty = $response.PSObject.Properties['value']
        return ($null -ne $valueProperty -and $valueProperty.Value -is [array] -and $valueProperty.Value.Count -eq 0)
    }
    catch { return $false }
}

function Invoke-ProbeAz {
    param([string[]]$Arguments, [string]$ErrorFile, [string]$OutputFile)
    $previousPreference = $ErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        $ErrorActionPreference = 'Continue'
        # Native commands update this global variable. A local sentinel would
        # shadow it and falsely report failed login even when the CLI succeeds.
        $global:LASTEXITCODE = 1
        if ($OutputFile) {
            & $azCommand.Source @Arguments 1>$OutputFile 2>$ErrorFile
        }
        else {
            & $azCommand.Source @Arguments 1>$null 2>$ErrorFile
        }
        return $global:LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Get-SearchDiagnosticMetadata {
    param([string]$Detail)
    # Extract only a bounded numeric status from CLI's verbose response log,
    # never a raw header/body, URL, token, path, count or arbitrary error message.
    $httpStatus = 'UNKNOWN'
    $statusMatches = [regex]::Matches($Detail,
        '(?im)\bResponse status(?: code)?:\s*(?<status>[1-5][0-9]{2})(?:\s|$)')
    if ($statusMatches.Count -gt 0) {
        $httpStatus = $statusMatches[$statusMatches.Count - 1].Groups['status'].Value
    }
    $errorKind = 'NONE_RECOGNIZED'
    if ([string]::IsNullOrWhiteSpace($Detail)) {
        $errorKind = 'EMPTY_DIAGNOSTICS'
    }
    elseif ($Detail -match "(?i)'int' object (?:is not iterable|has no attribute)") {
        $errorKind = 'CLI_SCALAR_RESPONSE'
    }
    elseif ($Detail -match '\bJSONDecodeError\b|\bDeserializationError\b') {
        $errorKind = 'CLI_JSON_PROCESSING'
    }
    elseif ($Detail -match '\bTypeError\b|\bAttributeError\b|\bValueError\b') {
        $errorKind = 'CLI_RESPONSE_PROCESSING'
    }
    elseif ($Detail -match 'unrecognized arguments|invalid choice|usage: az') {
        $errorKind = 'CLI_ARGUMENTS'
    }
    elseif ($Detail -match 'was unexpected at this time|syntax of the command is incorrect|not recognized as an internal or external command') {
        $errorKind = 'SHELL_SYNTAX'
    }
    $requestId = 'UNKNOWN'
    $contentType = 'UNKNOWN'
    # CLI logs headers as quoted name/value lines. Read only the final RESPONSE
    # header block, not request headers or body text that may mention headers.
    $headerBlocks = [regex]::Matches($Detail,
        '(?is)Response headers:[^\r\n]*\r?\n(?<headers>.*?)Response content:')
    if ($headerBlocks.Count -gt 0) {
        $headers = $headerBlocks[$headerBlocks.Count - 1].Groups['headers'].Value
        $idMatch = [regex]::Match($headers,
            '(?im)^\s*(?:INFO:\s*)?[''"](?:request-id|x-ms-request-id)[''"]:\s*[''"](?<id>[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})[''"]\s*$')
        if ($idMatch.Success) { $requestId = $idMatch.Groups['id'].Value }
        $typeMatch = [regex]::Match($headers,
            '(?im)^\s*(?:INFO:\s*)?[''"]content-type[''"]:\s*[''"](?<type>application/json|text/html|text/plain)(?:;[^''"\r\n]*)?[''"]\s*$')
        if ($typeMatch.Success) { $contentType = $typeMatch.Groups['type'].Value.ToLowerInvariant() }
    }
    [pscustomobject]@{ HttpStatus = $httpStatus; ErrorKind = $errorKind; RequestId = $requestId; ContentType = $contentType }
}

function Get-ProbeCliVersion {
    param([string]$OutputFile)
    try {
        $versionInfo = Get-Content -LiteralPath $OutputFile -Raw -ErrorAction Stop |
            ConvertFrom-Json -ErrorAction Stop
        $property = $versionInfo.PSObject.Properties['azure-cli']
        if ($property -and [string]$property.Value -cmatch '\A[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\z') {
            return [string]$property.Value
        }
    }
    catch { }
    return 'UNKNOWN'
}

function Get-SearchFailureMessage {
    param([string]$Detail)
    # Never echo raw service/CLI errors or credential-bearing inherited settings.
    $metadata = Get-SearchDiagnosticMetadata -Detail $Detail
    # Prefer an observed response status to numbers/keywords elsewhere in a log.
    $serviceDetail = if ($metadata.HttpStatus -ne 'UNKNOWN') {
        'HTTP ' + $metadata.HttpStatus
    } else { $Detail }
    if ($serviceDetail -match '\b403\b|forbidden|PermissionDenied') {
        return 'SEARCH_FORBIDDEN: check Search data-read role scope/propagation, service RBAC authentication mode AND network restrictions; a 403 alone does not distinguish them.'
    }
    if ($serviceDetail -match '\b401\b|unauthorized|AADSTS') {
        return 'SEARCH_AUTHENTICATION_FAILED: verify the selected identity, tenant, Search token audience and service authentication mode.'
    }
    if ($serviceDetail -match '\b404\b|IndexNotFound|ResourceNotFound|Not Found') {
        return 'SEARCH_NOT_FOUND: verify the endpoint, exact index name and supported API; do not create an index automatically.'
    }
    if ($serviceDetail -match '\b429\b|TooManyRequests|rate.?limit') {
        return 'SEARCH_THROTTLED: check service capacity and rate limits; this script does not retry the request.'
    }
    if ($serviceDetail -match '\b5[0-9]{2}\b|ServiceUnavailable|InternalServerError|BadGateway') {
        return 'SEARCH_SERVICE_ERROR: a server-side failure was reported; check service health with the owner, not broader permissions.'
    }
    if ($serviceDetail -match 'resolve|NameResolution|timed out|timeout|certificate|SSL|connection|proxy') {
        return 'SEARCH_CONNECTIVITY_FAILED: inspect private DNS, routes, firewall, proxy and approved CA trust.'
    }
    if ($serviceDetail -match '\b400\b|Bad\s?Request|InvalidRequestParameter|InvalidApiVersionParameter|unsupported|unrecognized arguments') {
        return 'SEARCH_REQUEST_REJECTED: check CLI/API compatibility and service/index policy; do not disable document permissions to make the check pass.'
    }
    if ($metadata.HttpStatus -match '\A2[0-9]{2}\z' -or
        $metadata.ErrorKind -in @('CLI_SCALAR_RESPONSE', 'CLI_JSON_PROCESSING', 'CLI_RESPONSE_PROCESSING')) {
        return 'SEARCH_CLI_PROCESSING_FAILED: Azure CLI reported a processing failure; this does not establish that Search rejected the request. Inspect the safe diagnostic summary.'
    }
    if ($metadata.ErrorKind -in @('CLI_ARGUMENTS', 'SHELL_SYNTAX')) {
        return 'SEARCH_CLI_INVOCATION_FAILED: check CLI version and command parsing; do not change Search permissions based on this result.'
    }
    return 'SEARCH_READ_FAILED: have the authorized administrator inspect service and CLI diagnostics securely.'
}

if (-not $ApprovedAzureHost -or
    [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Write-Output 'HOST_REQUIRED: run only on the approved Azure Windows VM with the selected identity/index authorized; include -ApprovedAzureHost.'
    exit 2
}
if ($ClientId -notmatch '\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\z' -or
    $ClientId -eq '00000000-0000-0000-0000-000000000000') {
    Write-Output 'CONFIGURATION_ERROR: provide the approved user-assigned managed identity client UUID, not a secret.'
    exit 2
}
try {
    $request = New-SearchProbeRequest -Endpoint $Endpoint -IndexName $IndexName -Operation $Operation -ApiVersion $ApiVersion
}
catch {
    Write-Output 'CONFIGURATION_ERROR: provide an HTTPS Search service endpoint and valid lowercase index name without paths, credentials or query parameters.'
    exit 2
}
$azCommand = Get-Command az -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $azCommand) {
    Write-Output 'PREREQUISITE_MISSING: Azure CLI must be installed on the VM and available on PATH.'
    exit 2
}

$savedEnvironment = @{}
foreach ($name in @(
    'AZURE_CONFIG_DIR', 'AZURE_CORE_COLLECT_TELEMETRY', 'NO_PROXY',
    'AZURE_CLIENT_SECRET', 'AZURE_CLIENT_CERTIFICATE_PATH',
    'AZURE_FEDERATED_TOKEN_FILE', 'AZURE_SEARCH_API_KEY', 'AZURE_SEARCH_KEY'
)) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$scratch = $null
$exitCode = 2
try {
    $scratch = Join-Path ([System.IO.Path]::GetTempPath()) (
        'elv-search-probe-' + [Guid]::NewGuid().ToString('N')
    )
    New-Item -ItemType Directory -Path $scratch | Out-Null

    # Secure the empty parent BEFORE the CLI can write tokens/cache files.
    # Host administrators still control the machine; this is not MI isolation.
    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $systemSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
    $acl = [System.Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($currentSid)
    $acl.SetAccessRuleProtection($true, $false)
    $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach ($sid in @($currentSid, $systemSid)) {
        $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
            $sid, [System.Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance, [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        ))
    }
    Set-Acl -LiteralPath $scratch -AclObject $acl
    $actualAcl = Get-Acl -LiteralPath $scratch
    if (-not $actualAcl.AreAccessRulesProtected) {
        throw 'Private cache ACL could not be verified.'
    }
    foreach ($rule in $actualAcl.GetAccessRules(
        $true, $true, [System.Security.Principal.SecurityIdentifier]
    )) {
        if ($rule.IdentityReference.Value -notin @($currentSid.Value, $systemSid.Value)) {
            throw 'Unexpected private cache ACL.'
        }
    }

    $env:AZURE_CONFIG_DIR = Join-Path $scratch 'azure'
    $env:AZURE_CORE_COLLECT_TELEMETRY = 'false'
    foreach ($name in @(
        'AZURE_CLIENT_SECRET', 'AZURE_CLIENT_CERTIFICATE_PATH',
        'AZURE_FEDERATED_TOKEN_FILE', 'AZURE_SEARCH_API_KEY', 'AZURE_SEARCH_KEY'
    )) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $env:NO_PROXY = ((@($savedEnvironment['NO_PROXY'],
        '169.254.169.254', '127.0.0.1', 'localhost') | Where-Object { $_ }) -join ',')
    $errorFile = Join-Path $scratch 'error.txt'

    $loginCode = Invoke-ProbeAz -Arguments @(
        'login', '--identity', '--client-id', $ClientId, '--allow-no-subscriptions',
        '--output', 'none', '--only-show-errors'
    ) -ErrorFile $errorFile
    if ($loginCode -ne 0) {
        Write-Output 'IDENTITY_LOGIN_FAILED: verify approved VM attachment, IMDS access and Azure CLI support. No Search request was attempted.'
        $exitCode = 3
    }
    else {
        # Both operations are data-plane reads, not indexing/schema management.
        # CLI acquires the Search token internally: no token in shell arguments.
        $readArguments = @(
            'rest', '--method', $request.Method, '--url', $request.Url,
            '--resource', 'https://search.azure.com',
            '--output', 'none'
        )
        $requestHeaders = @()
        $responseFile = Join-Path $scratch 'query-response.json'
        if ($Operation -eq 'Query') {
            $bodyFile = Join-Path $scratch 'query-request.json'
            [System.IO.File]::WriteAllText($bodyFile, $request.Body, [System.Text.Encoding]::ASCII)
            $readArguments += @('--body', ('@' + $bodyFile), '--output-file', $responseFile)
            $requestHeaders += 'Content-Type=application/json'
        }
        $clientRequestId = [Guid]::NewGuid().ToString('D')
        if ($Diagnostics) { $requestHeaders += ('x-ms-client-request-id=' + $clientRequestId) }
        if ($requestHeaders.Count -gt 0) { $readArguments += @('--headers') + $requestHeaders }
        # Verbose logging is opt-in, private and ephemeral. Do not use --debug
        # or mix --only-show-errors with --verbose (it would hide status logs).
        if ($Diagnostics) { $readArguments += '--verbose' }
        else { $readArguments += '--only-show-errors' }
        $requestUtc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
        $readCode = Invoke-ProbeAz -Arguments $readArguments -ErrorFile $errorFile
        $detail = Get-Content -LiteralPath $errorFile -Raw -ErrorAction SilentlyContinue
        $metadata = Get-SearchDiagnosticMetadata -Detail $detail
        if ($Diagnostics) {
            Write-Output ('SEARCH_REQUEST: operation={0}; api_version={1}; utc={2}; client_request_id={3}; service_request_id={4}; response_type={5}; http_status={6}' -f
                $Operation, $ApiVersion, $requestUtc, $clientRequestId, $metadata.RequestId, $metadata.ContentType, $metadata.HttpStatus)
        }
        if ($readCode -eq 0) {
            if ($Operation -eq 'Query' -and (
                -not (Test-EmptySearchResponse -OutputFile $responseFile) -or
                ($metadata.HttpStatus -ne 'UNKNOWN' -and $metadata.HttpStatus -ne '200')
            )) {
                Write-Output 'SEARCH_RESPONSE_UNEXPECTED: a complete zero-document response was not confirmed; no response body is displayed and the probe has not passed.'
                $exitCode = 4
            }
            else {
                if ($Operation -eq 'Count') {
                    Write-Output 'SEARCH_READ_SUCCEEDED: the explicitly selected managed identity completed a document-count request for this index from this host.'
                }
                else {
                    Write-Output 'SEARCH_QUERY_SUCCEEDED: the explicitly selected managed identity completed the fixed top=0 query; the returned document array is empty.'
                }
                Write-Output 'No document content was requested. Counts and tokens were not displayed; an empty index is a valid result.'
                Write-Output 'Schemas, analyzers, vector/semantic queries, document-level authorization, other indexes and full PoC compatibility were NOT validated.'
                $exitCode = 0
            }
        }
        else {
            $detail = Get-Content -LiteralPath $errorFile -Raw -ErrorAction SilentlyContinue
            Write-Output (Get-SearchFailureMessage -Detail $detail)
            if ($Diagnostics) {
                $metadata = Get-SearchDiagnosticMetadata -Detail $detail
                $versionFile = Join-Path $scratch 'cli-version.json'
                $versionError = Join-Path $scratch 'cli-version-error.txt'
                $versionCode = Invoke-ProbeAz -Arguments @(
                    'version', '--output', 'json', '--only-show-errors'
                ) -ErrorFile $versionError -OutputFile $versionFile
                $cliVersion = 'UNKNOWN'
                if ($versionCode -eq 0) {
                    $cliVersion = Get-ProbeCliVersion -OutputFile $versionFile
                }
                Write-Output ('SEARCH_DIAGNOSTICS: cli_exit={0}; http_status={1}; error_kind={2}; cli_version={3}' -f
                    $readCode, $metadata.HttpStatus, $metadata.ErrorKind, $cliVersion)
            }
            $exitCode = 4
        }
    }
    Write-Output 'No indexes, documents, indexers, role assignments or configuration keys were changed. Raw CLI diagnostics are not printed.'
}
catch {
    Write-Output 'PROBE_ERROR: secure cache setup or probe execution failed; the administrator must inspect the host securely.'
    $exitCode = 2
}
finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
    if ($scratch -and (Test-Path -LiteralPath $scratch)) {
        try {
            Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction Stop
        }
        catch {
            Write-Output 'CLEANUP_FAILED: a private elv-search-probe-* directory remains in the operator temp directory; arrange secure cleanup.'
            $exitCode = 5
        }
    }
}
exit $exitCode