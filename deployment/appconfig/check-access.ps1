#Requires -Version 5.1
<#
.SYNOPSIS
    Read-only App Configuration probe for an approved Azure Windows VM.
.DESCRIPTION
    Requires Azure CLI and a user-assigned managed identity already attached to
    the execution VM. Uses a private temporary CLI configuration and explicitly
    selects that identity. Does not attach identities, assign roles, create
    stores, change keys, import a PoC, or print configuration values or tokens.
    Run as a script, not dot-sourced. Follow organizational script-signing policy.
#>
[CmdletBinding()]
param(
    [string]$Endpoint,
    [string]$ClientId,
    [switch]$ApprovedAzureHost
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $ApprovedAzureHost -or
    [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Write-Output 'HOST_REQUIRED: run only on an approved Azure Windows VM with the identity attached; acknowledge with -ApprovedAzureHost.'
    exit 2
}
# Restrict the token destination to commercial Azure App Configuration.
if ([string]::IsNullOrWhiteSpace($Endpoint) -or
    $Endpoint -cnotmatch '\Ahttps://[a-z0-9][a-z0-9-]*\.azconfig\.io/?\z') {
    Write-Output 'CONFIGURATION_ERROR: provide the approved HTTPS App Configuration endpoint.'
    exit 2
}
if ([string]::IsNullOrWhiteSpace($ClientId) -or
    $ClientId -notmatch '\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\z' -or
    $ClientId -eq '00000000-0000-0000-0000-000000000000') {
    Write-Output 'CONFIGURATION_ERROR: provide a user-assigned managed identity client UUID, not a secret.'
    exit 2
}
$azCommand = Get-Command az -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $azCommand) {
    Write-Output 'PREREQUISITE_MISSING: Azure CLI must be installed on the VM and available on PATH.'
    exit 2
}

function Invoke-ProbeAz {
    param([string[]]$Arguments, [string]$ErrorFile)
    # Windows PowerShell 5.1 can turn native stderr into ErrorRecord objects.
    # Keep it out of user-visible output, and use the native exit code instead.
    $previousPreference = $ErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        $ErrorActionPreference = 'Continue'
        # A failure to launch az.cmd must not reuse a previous successful code.
        # Native commands update the global automatic variable. A local sentinel
        # shadows that result and makes even successful logins appear to fail.
        $global:LASTEXITCODE = 1
        & $azCommand.Source @Arguments 1>$null 2>$ErrorFile
        return $global:LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

$savedEnvironment = @{}
foreach ($name in @(
    'AZURE_CONFIG_DIR', 'AZURE_CORE_COLLECT_TELEMETRY', 'NO_PROXY',
    'AZURE_APPCONFIG_CONNECTION_STRING', 'AZURE_CLIENT_SECRET',
    'AZURE_CLIENT_CERTIFICATE_PATH', 'AZURE_FEDERATED_TOKEN_FILE'
)) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

$scratch = $null
$exitCode = 2
try {
    $scratch = Join-Path ([System.IO.Path]::GetTempPath()) (
        'elv-appconfig-probe-' + [Guid]::NewGuid().ToString('N')
    )
    New-Item -ItemType Directory -Path $scratch -ErrorAction Stop | Out-Null

    # Lock down the empty directory BEFORE Azure CLI can write a token/cache.
    # The current Windows identity and SYSTEM are the only explicit grantees.
    # Host administrators still control the VM; this is not an admin boundary.
    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $systemSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
    $acl = [System.Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($currentSid)
    $acl.SetAccessRuleProtection($true, $false)
    $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach ($sid in @($currentSid, $systemSid)) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
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
        'AZURE_APPCONFIG_CONNECTION_STRING', 'AZURE_CLIENT_SECRET',
        'AZURE_CLIENT_CERTIFICATE_PATH', 'AZURE_FEDERATED_TOKEN_FILE'
    )) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    # Environment names are case-insensitive on Windows. Retain existing bypasses.
    $env:NO_PROXY = ((@($savedEnvironment['NO_PROXY'],
        '169.254.169.254', '127.0.0.1', 'localhost') | Where-Object { $_ }) -join ',')
    $errorFile = Join-Path $scratch 'error.txt'

    $loginCode = Invoke-ProbeAz -Arguments @(
        'login', '--identity', '--client-id', $ClientId, '--allow-no-subscriptions',
        '--output', 'none', '--only-show-errors'
    ) -ErrorFile $errorFile
    if ($loginCode -ne 0) {
        Write-Output 'IDENTITY_LOGIN_FAILED: verify approved VM attachment, IMDS access and Azure CLI support.'
        Write-Output 'No App Configuration request was attempted. Raw CLI diagnostics are not printed.'
        $exitCode = 3
    }
    else {
        $readCode = Invoke-ProbeAz -Arguments @(
            'appconfig', 'kv', 'list', '--endpoint', $Endpoint, '--auth-mode', 'login',
            '--key', '*', '--label', '*', '--fields', 'key', '--top', '1',
            '--output', 'none', '--only-show-errors'
        ) -ErrorFile $errorFile
        if ($readCode -eq 0) {
            Write-Output 'READ_SUCCEEDED: the explicitly selected managed identity can list key metadata from this host.'
            Write-Output 'An empty store is a valid result. No keys, values or tokens were displayed.'
            Write-Output 'Write/update/delete rights, store creation and PoC configuration alignment were NOT tested.'
            $exitCode = 0
        }
        else {
            $detail = Get-Content -LiteralPath $errorFile -Raw -ErrorAction SilentlyContinue
            if ($detail -match '403|forbidden') {
                Write-Output 'READ_FORBIDDEN: check role scope/propagation AND network restrictions; a 403 alone does not distinguish them.'
            }
            elseif ($detail -match '401|unauthorized|AADSTS') {
                Write-Output 'READ_AUTHENTICATION_FAILED: verify token/tenant and the approved identity configuration.'
            }
            elseif ($detail -match 'resolve|NameResolution|timed out|timeout|certificate|SSL|connection') {
                Write-Output 'READ_CONNECTIVITY_FAILED: inspect private DNS, routes, firewall, proxy and approved CA trust.'
            }
            else {
                Write-Output 'READ_FAILED: have the VM administrator investigate CLI/service compatibility and access.'
            }
            Write-Output 'No configuration was changed. Raw CLI diagnostics are not printed.'
            $exitCode = 4
        }
    }
}
catch {
    # Exception text can contain raw CLI details, paths or inherited settings.
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
            Write-Output 'CLEANUP_FAILED: a private elv-appconfig-probe-* directory remains in the operator temp directory; arrange secure cleanup.'
            $exitCode = 5
        }
    }
}

exit $exitCode