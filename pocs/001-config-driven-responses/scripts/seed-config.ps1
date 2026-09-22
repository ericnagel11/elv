#Requires -Version 5.1
<#
.SYNOPSIS
    Add missing healthcare settings to existing App Configuration stores.
.DESCRIPTION
    Requires an existing Azure CLI sign-in and permission to the named stores.
    No sign-in, provisioning, index changes, bulk import, export, or deletion.
    Default: add missing keys only. -WhatIf performs scoped reads but no writes.
    -OverwriteExisting opts into replacing selected existing values. Review a
    WhatIf run first; take any required backup separately in a protected location.
    Values, credentials and CLI error bodies are never printed by this script.

    Keys are exact fully-qualified seed keys, never wildcard patterns. Labels
    are baseline/candidate in production; only candidate exists in draft.
    Existing knowledge:index is preserved even with -OverwriteExisting unless
    -KnowledgeIndex is explicitly supplied and that key is in the selected scope.
    -SkipKnowledge takes precedence over knowledge keys in -Keys.

    az appconfig kv set currently documents no --if-match/--if-none-match flags:
    https://learn.microsoft.com/cli/azure/appconfig/kv#az-appconfig-kv-set
    If installed CLI help exposes both, pass the observed ETag for updates and
    '*' for create-only writes. Otherwise re-read exact key/label/ETag immediately
    before writing and warn: this is NOT an atomic compare-and-set guarantee.
    The CLI can internally re-read/retry; concurrent writers must be paused in
    that fallback mode. Never silently claim race-free migration.

    Writes stop at the first failure; prior successful keys are not rolled back.
    Seed changes are outside application-recorded change history.
.EXAMPLE
    ./scripts/seed-config.ps1 -AppConfigName cfgresp1234-appcfg -WhatIf
.EXAMPLE
    ./scripts/seed-config.ps1 -AppConfigName cfgresp1234-appcfg -DraftAppConfigName cfgresp1234-draft -Keys experience:persona,knowledge:filter -Labels candidate -OverwriteExisting -WhatIf
.EXAMPLE
    ./scripts/seed-config.ps1 -AppConfigName cfgresp1234-appcfg -Keys knowledge:index -KnowledgeIndex medical-policies-vector -OverwriteExisting -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$AppConfigName,
    [string]$DraftAppConfigName,
    [ValidateSet('login', 'key')][string]$AuthMode = 'login',
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{1,127}$')][string]$KnowledgeIndex = 'kb-current',
    [switch]$SkipKnowledge,
    [switch]$OverwriteExisting,
    [ValidateNotNullOrEmpty()]
    [ValidateSet('experience:persona', 'experience:tone', 'experience:verbosity',
        'experience:reading_level', 'experience:response_structure', 'experience:prompt_asset',
        'knowledge:enabled', 'knowledge:index', 'knowledge:filter', 'knowledge:top_k',
        'knowledge:query_mode', 'knowledge:citation_style')]
    [string[]]$Keys,
    [ValidateNotNullOrEmpty()][ValidateSet('baseline', 'candidate')]
    [string[]]$Labels = @('baseline', 'candidate')
)

$ErrorActionPreference = 'Stop'
$indexExplicit = $PSBoundParameters.ContainsKey('KnowledgeIndex')
if ($KnowledgeIndex -cnotmatch '^[a-z0-9][a-z0-9_-]{1,127}$' -or
    $KnowledgeIndex.Contains('--') -or $KnowledgeIndex.Contains('__')) {
    throw 'KnowledgeIndex must use 2-128 lowercase letters, digits, dashes or underscores, start with a letter or digit, and have no consecutive dashes or underscores.'
}

function Invoke-SeedAz {
    param([string[]]$Arguments)
    # PS5.1 native executables update GLOBAL LASTEXITCODE, not a local shadow.
    $previousExit = Get-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    $hadExit = $null -ne $previousExit
    $savedExit = if ($hadExit) { $previousExit.Value } else { $null }
    $global:LASTEXITCODE = -1
    try {
        # Capture stderr as well, without leaking error bodies/values to output.
        $ErrorActionPreference = 'Continue'
        $output = @(& az @Arguments 2>&1)
        $exitCode = $global:LASTEXITCODE
        if ($exitCode -ne 0) {
            throw 'Azure CLI operation failed. Check sign-in, permissions, connectivity and CLI support; no further keys were written.'
        }
        return ($output -join [Environment]::NewLine)
    }
    catch {
        throw 'Azure CLI operation failed. Check sign-in, permissions, connectivity and CLI support; no further keys were written.'
    }
    finally {
        if ($hadExit) { $global:LASTEXITCODE = $savedExit }
        else { Remove-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue }
    }
}

function Get-SeedEntry {
    param([string]$Store, [string]$Key, [string]$Label)
    # Exact allowed keys/labels only. Do not read values or resolve Key Vault.
    $json = Invoke-SeedAz @('appconfig', 'kv', 'list', '--name', $Store,
        '--key', $Key, '--label', $Label, '--auth-mode', $AuthMode,
        '--fields', 'key', 'label', 'etag', 'locked', '--all',
        '--output', 'json', '--only-show-errors')
    try {
        if (-not $json.Trim().StartsWith('[')) { throw 'Expected a list.' }
        $decoded = ConvertFrom-Json -InputObject $json
        # Normalize array enumeration differences between Windows PS5.1 and PS7.
        $items = @($decoded | Where-Object { $null -ne $_ })
        if ($items.Count -gt 1) { throw 'Ambiguous result.' }
        if ($items.Count -eq 1) {
            $item = $items[0]
            if ($item.key -cne $Key -or $item.label -cne $Label -or
                [string]::IsNullOrWhiteSpace($item.etag) -or
                $item.locked -isnot [bool]) { throw 'Invalid result.' }
            return $item
        }
    }
    catch {
        throw 'Could not verify the exact key, label and ETag. No further keys were written.'
    }
    return $null
}

$baseline = [ordered]@{
    'experience:persona' = 'a Contoso Health Plan member support agent'
    'experience:tone' = 'neutral and professional'
    'experience:verbosity' = 'brief'
    'experience:reading_level' = 'grade 9'
    'experience:response_structure' = 'a single short paragraph'
    'experience:prompt_asset' = 'response:v1'
}
$candidate = [ordered]@{
    'experience:persona' = 'a caring Contoso Health Plan member support specialist'
    'experience:tone' = 'warm, friendly, and empathetic'
    'experience:verbosity' = 'concise but complete'
    'experience:reading_level' = 'grade 6'
    'experience:response_structure' = 'a one-sentence acknowledgement, then 2 to 3 short bullet points, then a clear next step'
    'experience:prompt_asset' = 'response:v2'
}
$knowledge = [ordered]@{
    'knowledge:enabled' = 'true'
    'knowledge:index' = $KnowledgeIndex
    'knowledge:filter' = "industry eq 'healthcare' and status eq 'approved'"
    'knowledge:top_k' = '3'
    'knowledge:query_mode' = 'simple'
    'knowledge:citation_style' = 'inline'
}
$targets = @(
    @{ Store = $AppConfigName; Label = 'baseline'; Profile = $baseline }
    @{ Store = $AppConfigName; Label = 'candidate'; Profile = $candidate }
)
if ($DraftAppConfigName) {
    if ($DraftAppConfigName -ieq $AppConfigName) {
        throw 'Production and draft must name different existing stores.'
    }
    $targets += @{ Store = $DraftAppConfigName; Label = 'candidate'; Profile = $candidate }
}

# Resolve the entire scoped plan before any writes. Keep values out of previews.
$plan = @()
foreach ($target in $targets) {
    if ($Labels -notcontains $target.Label) { continue }
    $settings = [ordered]@{}
    foreach ($key in $target.Profile.Keys) { $settings[$key] = $target.Profile[$key] }
    if (-not $SkipKnowledge) {
        foreach ($key in $knowledge.Keys) { $settings[$key] = $knowledge[$key] }
    }
    foreach ($key in $settings.Keys) {
        if ($Keys -and $Keys -notcontains $key) { continue }
        $existing = Get-SeedEntry $target.Store $key $target.Label
        $action = 'Add missing'
        if ($null -ne $existing) {
            if (-not $OverwriteExisting -or ($key -eq 'knowledge:index' -and -not $indexExplicit)) {
                Write-Host "Preserve existing: $($target.Store) / $($target.Label) / $key"
                continue
            }
            if ($existing.locked) { throw 'A selected key is locked. No seed writes were started.' }
            $action = 'Overwrite existing'
        }
        $plan += [pscustomobject]@{
            Store = $target.Store; Label = $target.Label; Key = $key
            Value = $settings[$key]; Existing = $existing; Action = $action
        }
    }
}

$conditionalFlags = $false
if ($plan.Count -gt 0) {
    $helpText = Invoke-SeedAz @('appconfig', 'kv', 'set', '--help')
    $conditionalFlags = $helpText.Contains('--if-match') -and $helpText.Contains('--if-none-match')
    if (-not $conditionalFlags) {
        Write-Warning 'This CLI exposes no conditional-write flags. ETags will be rechecked, but a race remains between read and write (including CLI retries). Pause concurrent writers before applying; this is not an atomic migration.'
    }
}

$written = 0
foreach ($entry in $plan) {
    $description = "$($entry.Store) / $($entry.Label) / $($entry.Key) (values hidden)"
    if (-not $PSCmdlet.ShouldProcess($description, $entry.Action)) { continue }

    $fresh = Get-SeedEntry $entry.Store $entry.Key $entry.Label
    if ($null -eq $entry.Existing) {
        if ($null -ne $fresh) {
            throw 'A key appeared after preview. Stopped without overwriting it; earlier successful writes remain.'
        }
    }
    elseif ($null -eq $fresh -or $fresh.etag -cne $entry.Existing.etag -or $fresh.locked) {
        throw 'A key changed or became locked after preview. Stopped; earlier successful writes remain.'
    }

    $arguments = @('appconfig', 'kv', 'set', '--name', $entry.Store,
        '--key', $entry.Key, '--label', $entry.Label, '--value', $entry.Value,
        '--auth-mode', $AuthMode, '--yes', '--output', 'none', '--only-show-errors')
    if ($conditionalFlags) {
        if ($null -eq $entry.Existing) { $arguments += @('--if-none-match', '*') }
        else { $arguments += @('--if-match', $entry.Existing.etag) }
    }
    # Omit tags/content-type so the CLI preserves existing metadata.
    $null = Invoke-SeedAz $arguments
    $written++
    Write-Host "Written: $description"
}
Write-Host "Done. $written key(s) written. Seed changes are outside application-recorded history."
