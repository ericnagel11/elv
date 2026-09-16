#Requires -Version 5.1
<#
.SYNOPSIS
    Read-only, one-container Blob listing probe for an approved Azure Windows VM.
.DESCRIPTION
    Uses an explicitly selected VM-attached user-assigned managed identity and
    an isolated, private Azure CLI cache. Lists at most one blob, without extra
    metadata/tags/snapshots or downloading file contents. Names, properties,
    continuation markers, tokens and raw diagnostics are not displayed.
    Uses the standard commercial Azure Blob endpoint for the supplied account,
    not a route-specific public endpoint. Never queries storage keys, generates
    SAS, changes resources, or validates Search-indexer-to-Blob access.
    Requires Azure CLI, not Python/PoC packages. Run with &, never dot-source,
    and follow the customer's script-signing policy.
#>
[CmdletBinding()]
param(
    [string]$AccountName,
    [string]$ContainerName,
    [string]$ClientId,
    [switch]$ApprovedAzureHost,
    [switch]$Diagnostics
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function New-BlobListArguments {
    param([string]$AccountName, [string]$ContainerName)
    if ($AccountName -cnotmatch '\A[a-z0-9]{3,24}\z') {
        throw 'Provide a 3-24 character lowercase storage account name, not an endpoint or credential.'
    }
    if ($ContainerName -cnotmatch '\A[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\z' -or
        $ContainerName.Contains('--')) {
        throw 'Provide one approved existing 3-63 character lowercase container name.'
    }
    # Explicit endpoint prevents inherited storage configuration redirecting the
    # token. Standard DNS supports Private Link; microsoftrouting is not Private Link.
    @(
        'storage', 'blob', 'list', '--account-name', $AccountName,
        '--blob-endpoint', ('https://' + $AccountName + '.blob.core.windows.net/'),
        '--container-name', $ContainerName, '--auth-mode', 'login',
        '--num-results', '1', '--timeout', '30', '--show-next-marker', '--output', 'none'
    )
    # show-next-marker keeps the marker in suppressed stdout instead of warnings.
    # No marker is followed by this script. The CLI/SDK may retry failed requests.
}

function Invoke-ProbeAz {
    param([string[]]$Arguments, [string]$ErrorFile, [string]$OutputFile)
    $previousPreference = $ErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        $ErrorActionPreference = 'Continue'
        # Native commands update the global automatic variable, not a local copy.
        $global:LASTEXITCODE = 1
        if ($OutputFile) {
            & $azCommand.Source @Arguments 1>$OutputFile 2>$ErrorFile
        }
        else {
            & $azCommand.Source @Arguments 1>$null 2>$ErrorFile
        }
        return $global:LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
}

function Get-BlobDiagnosticMetadata {
    param([string]$Detail)
    $status = 'UNKNOWN'
    $statusMatches = [regex]::Matches($Detail,
        '(?im)\bResponse status(?: code)?:\s*(?<status>[1-5][0-9]{2})(?:\s|$)')
    if ($statusMatches.Count -gt 0) {
        $status = $statusMatches[$statusMatches.Count - 1].Groups['status'].Value
    }
    # Only return constants from this allowlist, never arbitrary service text.
    $storageCode = 'UNKNOWN'
    foreach ($code in @(
        'AuthorizationPermissionMismatch', 'AuthorizationFailure',
        'AuthenticationFailed', 'InvalidAuthenticationInfo', 'NoAuthenticationInformation',
        'ContainerNotFound', 'ResourceNotFound', 'AccountIsDisabled',
        'ServerBusy', 'InternalError', 'OperationTimedOut',
        'InvalidResourceName', 'InvalidQueryParameterValue'
    )) {
        if ($Detail -match ('(?i)\b' + $code + '\b')) { $storageCode = $code; break }
    }
    $kind = 'NONE_RECOGNIZED'
    if ([string]::IsNullOrWhiteSpace($Detail)) { $kind = 'EMPTY_DIAGNOSTICS' }
    elseif ($Detail -match 'was unexpected at this time|syntax of the command is incorrect|not recognized as an internal or external command') { $kind = 'SHELL_SYNTAX' }
    elseif ($Detail -match 'unrecognized arguments|invalid choice|usage: az') { $kind = 'CLI_ARGUMENTS' }
    elseif ($Detail -match '\bTypeError\b|\bAttributeError\b|\bJSONDecodeError\b|\bDeserializationError\b') { $kind = 'CLI_PROCESSING' }
    [pscustomobject]@{ HttpStatus = $status; StorageCode = $storageCode; ErrorKind = $kind }
}

function Get-BlobFailureMessage {
    param([string]$Detail)
    $metadata = Get-BlobDiagnosticMetadata -Detail $Detail
    if ($metadata.ErrorKind -in @('SHELL_SYNTAX', 'CLI_ARGUMENTS')) {
        return 'BLOB_CLI_INVOCATION_FAILED: check CLI support and command parsing; do not change Azure permissions based on this result.'
    }
    $serviceDetail = if ($metadata.HttpStatus -ne 'UNKNOWN') { 'HTTP ' + $metadata.HttpStatus } else { $Detail }
    if ($serviceDetail -match '\b403\b|forbidden' -or $metadata.StorageCode -in @('AuthorizationPermissionMismatch', 'AuthorizationFailure', 'AccountIsDisabled')) {
        return 'BLOB_FORBIDDEN: check Blob data-read role scope/propagation, account policy and network restrictions; this is not automatic evidence a broader role is needed.'
    }
    if ($serviceDetail -match '\b401\b|unauthorized|AADSTS' -or $metadata.StorageCode -in @('AuthenticationFailed', 'InvalidAuthenticationInfo', 'NoAuthenticationInformation')) {
        return 'BLOB_AUTHENTICATION_FAILED: verify the selected identity, tenant and Storage token authentication.'
    }
    if ($serviceDetail -match '\b404\b|Not Found' -or $metadata.StorageCode -in @('ContainerNotFound', 'ResourceNotFound')) {
        return 'BLOB_NOT_FOUND: verify the account and exact container name on the standard Blob endpoint; do not create another container automatically.'
    }
    if ($serviceDetail -match '\b429\b|TooManyRequests') {
        return 'BLOB_THROTTLED: check storage limits with the owner; do not repeatedly rerun the probe.'
    }
    if ($serviceDetail -match '\b5[0-9]{2}\b' -or $metadata.StorageCode -in @('ServerBusy', 'InternalError', 'OperationTimedOut')) {
        return 'BLOB_SERVICE_ERROR: a server-side failure was reported; investigate with the owner rather than broadening permissions.'
    }
    if ($serviceDetail -match 'resolve|NameResolution|timed out|timeout|certificate|SSL|connection|proxy') {
        return 'BLOB_CONNECTIVITY_FAILED: check the standard Blob endpoint DNS, private route/firewall, proxy and approved CA trust.'
    }
    if ($serviceDetail -match '\b400\b|Bad\s?Request|unsupported' -or $metadata.StorageCode -in @('InvalidResourceName', 'InvalidQueryParameterValue')) {
        return 'BLOB_REQUEST_REJECTED: check CLI/service compatibility and approved account/container configuration.'
    }
    if ($metadata.HttpStatus -match '\A2[0-9]{2}\z' -or $metadata.ErrorKind -eq 'CLI_PROCESSING') {
        return 'BLOB_CLI_PROCESSING_FAILED: the CLI failed to process the request/result; successful Blob access is not yet established.'
    }
    return 'BLOB_READ_FAILED: inspect the safe diagnostics and have the authorized administrator investigate locally if needed.'
}

function Get-ProbeCliVersion {
    param([string]$OutputFile)
    try {
        $info = Get-Content -LiteralPath $OutputFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        $property = $info.PSObject.Properties['azure-cli']
        if ($property -and [string]$property.Value -cmatch '\A[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\z') {
            return [string]$property.Value
        }
    }
    catch { }
    return 'UNKNOWN'
}

if (-not $ApprovedAzureHost -or [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Write-Output 'HOST_REQUIRED: run only on the approved Azure Windows VM with this identity/account/container authorized; include -ApprovedAzureHost.'
    exit 2
}
if ($ClientId -notmatch '\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\z' -or
    $ClientId -eq '00000000-0000-0000-0000-000000000000') {
    Write-Output 'CONFIGURATION_ERROR: provide the approved user-assigned managed identity client UUID, not a secret.'
    exit 2
}
try { $listArguments = @(New-BlobListArguments -AccountName $AccountName -ContainerName $ContainerName) }
catch {
    Write-Output 'CONFIGURATION_ERROR: provide a valid storage account name and approved existing container name, not URLs, paths or credentials.'
    exit 2
}
$azCommand = Get-Command az -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $azCommand) {
    Write-Output 'PREREQUISITE_MISSING: Azure CLI must be installed on the VM and available on PATH.'
    exit 2
}

$clearEnvironment = @(
    'AZURE_CLIENT_SECRET', 'AZURE_CLIENT_CERTIFICATE_PATH', 'AZURE_FEDERATED_TOKEN_FILE',
    'AZURE_STORAGE_KEY', 'AZURE_STORAGE_SAS_TOKEN', 'AZURE_STORAGE_CONNECTION_STRING',
    'AZURE_STORAGE_ACCOUNT', 'AZURE_STORAGE_ACCOUNT_URL', 'AZURE_STORAGE_SERVICE_ENDPOINT',
    'AZURE_STORAGE_AUTH_MODE'
)
$savedEnvironment = @{}
foreach ($name in ($clearEnvironment + @(
    'AZURE_CONFIG_DIR', 'AZURE_CORE_COLLECT_TELEMETRY', 'AZURE_EXTENSION_USE_DYNAMIC_INSTALL', 'NO_PROXY'
))) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$scratch = $null
$exitCode = 2
try {
    $scratch = Join-Path ([System.IO.Path]::GetTempPath()) ('elv-blob-probe-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $scratch | Out-Null
    # Secure the empty parent BEFORE Azure CLI can write any token/cache. VM
    # administrators still control the host; this is not managed-identity isolation.
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
    if (-not $actualAcl.AreAccessRulesProtected) { throw 'Private cache ACL could not be verified.' }
    foreach ($rule in $actualAcl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])) {
        if ($rule.IdentityReference.Value -notin @($currentSid.Value, $systemSid.Value)) { throw 'Unexpected private cache ACL.' }
    }

    foreach ($name in $clearEnvironment) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
    $env:AZURE_CONFIG_DIR = Join-Path $scratch 'azure'
    $env:AZURE_CORE_COLLECT_TELEMETRY = 'false'
    $env:AZURE_EXTENSION_USE_DYNAMIC_INSTALL = 'no'
    $env:NO_PROXY = ((@($savedEnvironment['NO_PROXY'], '169.254.169.254', '127.0.0.1', 'localhost') |
        Where-Object { $_ }) -join ',')
    $errorFile = Join-Path $scratch 'error.txt'
    $stage = 'LOGIN'
    $operationCode = Invoke-ProbeAz -Arguments @(
        'login', '--identity', '--client-id', $ClientId, '--allow-no-subscriptions', '--output', 'none', '--only-show-errors'
    ) -ErrorFile $errorFile
    if ($operationCode -ne 0) {
        Write-Output 'IDENTITY_LOGIN_FAILED: verify VM identity attachment, IMDS access and CLI support. No Blob listing was attempted.'
        $exitCode = 3
    }
    else {
        $stage = 'LIST'
        if ($Diagnostics) { $listArguments += '--verbose' }
        else { $listArguments += '--only-show-errors' }
        $operationCode = Invoke-ProbeAz -Arguments $listArguments -ErrorFile $errorFile
        if ($operationCode -eq 0) {
            Write-Output 'BLOB_READ_SUCCEEDED: the explicitly selected managed identity completed a limited listing of the approved container from this VM.'
            Write-Output 'No file contents were downloaded; blob names, properties, continuation markers and tokens were not displayed. An empty container is a valid result.'
            Write-Output 'Individual blob downloads, uploads/deletes, Search-indexer access, private routing and full PoC operation were NOT validated.'
            $exitCode = 0
        }
        else {
            $detail = Get-Content -LiteralPath $errorFile -Raw -ErrorAction SilentlyContinue
            Write-Output (Get-BlobFailureMessage -Detail $detail)
            $exitCode = 4
        }
    }
    if ($exitCode -ne 0 -and $Diagnostics) {
        $detail = Get-Content -LiteralPath $errorFile -Raw -ErrorAction SilentlyContinue
        $metadata = Get-BlobDiagnosticMetadata -Detail $detail
        $versionFile = Join-Path $scratch 'cli-version.json'
        $versionCode = Invoke-ProbeAz -Arguments @('version', '--output', 'json', '--only-show-errors') `
            -ErrorFile (Join-Path $scratch 'cli-version-error.txt') -OutputFile $versionFile
        $cliVersion = 'UNKNOWN'
        if ($versionCode -eq 0) { $cliVersion = Get-ProbeCliVersion -OutputFile $versionFile }
        Write-Output ('BLOB_DIAGNOSTICS: stage={0}; cli_exit={1}; http_status={2}; storage_error={3}; error_kind={4}; cli_version={5}' -f
            $stage, $operationCode, $metadata.HttpStatus, $metadata.StorageCode, $metadata.ErrorKind, $cliVersion)
    }
    Write-Output 'No containers, blobs, access policies, role assignments or network settings were changed. Raw CLI diagnostics are not printed.'
}
catch {
    Write-Output 'PROBE_ERROR: secure cache setup or probe execution failed; the authorized administrator must inspect the host securely.'
    $exitCode = 2
}
finally {
    foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    if ($scratch -and (Test-Path -LiteralPath $scratch)) {
        try { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction Stop }
        catch {
            Write-Output 'CLEANUP_FAILED: a private elv-blob-probe-* directory remains in the operator temp directory; arrange secure local cleanup.'
            $exitCode = 5
        }
    }
}
exit $exitCode