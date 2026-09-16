#Requires -Version 5.1
<#
.SYNOPSIS
    Opt-in Azure OpenAI inference check for an approved Azure Windows VM.
.DESCRIPTION
    Uses an explicitly selected attached user-assigned managed identity and a
    private temporary Azure CLI cache. Sends only a fixed synthetic prompt with
    a 16-token output limit. This is a billable inference test, not a read-only
    metadata check. Does not provision resources, change deployments or RBAC,
    seed configuration, install dependencies, or display tokens/model output.
    Requires Azure CLI. Run normally with &, never by dot-sourcing, and follow
    organizational script-signing policy. Intended for GPT-4o chat deployments.
#>
[CmdletBinding()]
param(
    [string]$Endpoint,
    [string]$Deployment,
    [string]$ClientId,
    [switch]$ApprovedAzureHost,
    [switch]$AllowInference
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function New-InferenceRequest {
    param([string]$Endpoint, [string]$Deployment)
    # Only commercial Azure OpenAI account endpoints, not arbitrary token sinks.
    if ($Endpoint -cnotmatch '\Ahttps://[a-z0-9][a-z0-9-]*\.openai\.azure\.com/?\z') {
        throw 'Provide the approved HTTPS Azure OpenAI account endpoint, without a path or credentials.'
    }
    if ($Deployment -cnotmatch '\A[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\z') {
        throw 'Provide a deployment name of 1-64 ASCII letters, digits, dots, underscores or hyphens, starting with a letter or digit.'
    }
    [pscustomobject]@{
        Url = $Endpoint.TrimEnd('/') + '/openai/deployments/' + $Deployment +
            '/chat/completions?api-version=2024-10-21'
        Body = (@{
            messages = @(@{ role = 'user'; content = 'Reply with OK.' })
            max_tokens = 16
            n = 1
            stream = $false
        } | ConvertTo-Json -Depth 5 -Compress)
    }
}

function Invoke-ProbeAz {
    param([string[]]$Arguments, [string]$ErrorFile)
    $previousPreference = $ErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        $ErrorActionPreference = 'Continue'
        # Native commands update the global variable; never shadow it locally.
        $global:LASTEXITCODE = 1
        & $azCommand.Source @Arguments 1>$null 2>$ErrorFile
        return $global:LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Get-InferenceFailureMessage {
    param([string]$Detail)
    # Return only fixed categories. Raw diagnostics may contain sensitive data.
    if ($Detail -match '403|forbidden|PermissionDenied') {
        return 'INFERENCE_FORBIDDEN: check OpenAI inference RBAC AND resource network restrictions; a 403 alone does not distinguish them.'
    }
    if ($Detail -match '401|unauthorized|AADSTS') {
        return 'INFERENCE_AUTHENTICATION_FAILED: verify the approved identity, tenant and Cognitive Services token audience.'
    }
    if ($Detail -match '404|DeploymentNotFound|ResourceNotFound|Not Found') {
        return 'INFERENCE_NOT_FOUND: verify the account endpoint, deployment name, availability and API version; do not create a deployment automatically.'
    }
    if ($Detail -match '429|TooManyRequests|quota|rate.?limit') {
        return 'INFERENCE_THROTTLED: check model quota and rate limits; this script does not retry the inference call.'
    }
    if ($Detail -match 'resolve|NameResolution|timed out|timeout|certificate|SSL|connection|proxy') {
        return 'INFERENCE_CONNECTIVITY_FAILED: inspect private DNS, routes, firewall, proxy and approved CA trust.'
    }
    if ($Detail -match '400|Bad Request|unsupported|unrecognized arguments') {
        return 'INFERENCE_REQUEST_REJECTED: check CLI support, deployment/model/API compatibility and service policy.'
    }
    return 'INFERENCE_FAILED: have the authorized administrator inspect service and CLI diagnostics securely.'
}

# Refuse all authentication and network activity until both acknowledgements.
if (-not $ApprovedAzureHost -or
    [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Write-Output 'HOST_REQUIRED: run only on the approved Azure Windows VM with this identity attached; include -ApprovedAzureHost.'
    exit 2
}
if (-not $AllowInference) {
    Write-Output 'INFERENCE_APPROVAL_REQUIRED: include -AllowInference only to authorize the fixed synthetic prompt and its model-usage charge.'
    exit 2
}
if ($ClientId -notmatch '\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\z' -or
    $ClientId -eq '00000000-0000-0000-0000-000000000000') {
    Write-Output 'CONFIGURATION_ERROR: provide the approved user-assigned managed identity client UUID, not a secret.'
    exit 2
}
try {
    $request = New-InferenceRequest -Endpoint $Endpoint -Deployment $Deployment
}
catch {
    Write-Output ('CONFIGURATION_ERROR: ' + $_.Exception.Message)
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
    'AZURE_FEDERATED_TOKEN_FILE', 'AZURE_OPENAI_API_KEY', 'OPENAI_API_KEY'
)) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$scratch = $null
$exitCode = 2
try {
    $scratch = Join-Path ([System.IO.Path]::GetTempPath()) (
        'elv-openai-probe-' + [Guid]::NewGuid().ToString('N')
    )
    New-Item -ItemType Directory -Path $scratch | Out-Null

    # Secure the empty cache parent BEFORE Azure CLI runs. VM admins still have
    # host control; this is not an isolation boundary from other administrators.
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
        'AZURE_FEDERATED_TOKEN_FILE', 'AZURE_OPENAI_API_KEY', 'OPENAI_API_KEY'
    )) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $env:NO_PROXY = ((@($savedEnvironment['NO_PROXY'],
        '169.254.169.254', '127.0.0.1', 'localhost') | Where-Object { $_ }) -join ',')
    $errorFile = Join-Path $scratch 'error.txt'
    $bodyFile = Join-Path $scratch 'request.json'
    # File input avoids Windows PowerShell/native-command JSON quoting problems.
    [System.IO.File]::WriteAllText($bodyFile, $request.Body, [System.Text.Encoding]::ASCII)

    $loginCode = Invoke-ProbeAz -Arguments @(
        'login', '--identity', '--client-id', $ClientId, '--allow-no-subscriptions',
        '--output', 'none', '--only-show-errors'
    ) -ErrorFile $errorFile
    if ($loginCode -ne 0) {
        Write-Output 'IDENTITY_LOGIN_FAILED: verify approved VM attachment, IMDS access and Azure CLI support. No inference request was attempted.'
        $exitCode = 3
    }
    else {
        # Azure CLI acquires the correct audience token internally. No token is
        # placed in PowerShell output, variables, command arguments or body files.
        $inferenceCode = Invoke-ProbeAz -Arguments @(
            'rest', '--method', 'post', '--url', $request.Url,
            '--resource', 'https://cognitiveservices.azure.com/',
            '--headers', 'Content-Type=application/json', '--body', ('@' + $bodyFile),
            '--output', 'none', '--only-show-errors'
        ) -ErrorFile $errorFile
        if ($inferenceCode -eq 0) {
            Write-Output 'INFERENCE_SUCCEEDED: the explicitly selected managed identity completed the synthetic chat request to this deployment.'
            Write-Output 'No model text or tokens were displayed. Model snapshot/version, other services and full PoC operation were NOT validated.'
            $exitCode = 0
        }
        else {
            $detail = Get-Content -LiteralPath $errorFile -Raw -ErrorAction SilentlyContinue
            Write-Output (Get-InferenceFailureMessage -Detail $detail)
            $exitCode = 4
        }
    }
    Write-Output 'No resources, deployments, role assignments or App Configuration keys were changed. Raw CLI diagnostics are not printed.'
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
            Write-Output 'CLEANUP_FAILED: a private elv-openai-probe-* directory remains in the operator temp directory; arrange secure cleanup.'
            $exitCode = 5
        }
    }
}
exit $exitCode