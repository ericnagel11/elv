#Requires -Version 5.1
<#
.SYNOPSIS
    Seeds the baseline and candidate experience profiles into Azure App
    Configuration. Uses Entra ID (--auth-mode login), which requires the
    "App Configuration Data Owner" role that setup.ps1 assigns.

.EXAMPLE
    pwsh scripts/seed-config.ps1 -AppConfigName cfgresp1234-appcfg
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AppConfigName,
    [string]$DraftAppConfigName,
    [ValidateSet("login", "key")][string]$AuthMode = "login",
    [string]$KnowledgeIndex = "kb-current",
    [switch]$SkipKnowledge
)

$ErrorActionPreference = "Stop"

function Set-Kv {
    param([string]$Store, [string]$Key, [string]$Value, [string]$Label)
    az appconfig kv set --name $Store --key $Key --value $Value `
        --label $Label --auth-mode $AuthMode --yes | Out-Null
}

Write-Host "==> Seeding baseline profile..."
Set-Kv $AppConfigName "experience:persona" "a Contoso customer support agent" "baseline"
Set-Kv $AppConfigName "experience:tone" "neutral and professional" "baseline"
Set-Kv $AppConfigName "experience:verbosity" "brief" "baseline"
Set-Kv $AppConfigName "experience:reading_level" "grade 9" "baseline"
Set-Kv $AppConfigName "experience:response_structure" "a single short paragraph" "baseline"
Set-Kv $AppConfigName "experience:prompt_asset" "response:v1" "baseline"

Write-Host "==> Seeding candidate profile..."
Set-Kv $AppConfigName "experience:persona" "a caring Contoso customer support specialist" "candidate"
Set-Kv $AppConfigName "experience:tone" "warm, friendly, and empathetic" "candidate"
Set-Kv $AppConfigName "experience:verbosity" "concise but complete" "candidate"
Set-Kv $AppConfigName "experience:reading_level" "grade 6" "candidate"
Set-Kv $AppConfigName "experience:response_structure" "a one-sentence acknowledgement, then 2 to 3 short bullet points, then a clear next step" "candidate"
Set-Kv $AppConfigName "experience:prompt_asset" "response:v2" "candidate"

if ($DraftAppConfigName) {
    # The draft store holds the proposal the experience designer works on. The
    # approver publishes it into the production candidate profile.
    Write-Host "==> Seeding the draft store $DraftAppConfigName..."
    Set-Kv $DraftAppConfigName "experience:persona" "a caring Contoso customer support specialist" "candidate"
    Set-Kv $DraftAppConfigName "experience:tone" "warm, friendly, and empathetic" "candidate"
    Set-Kv $DraftAppConfigName "experience:verbosity" "concise but complete" "candidate"
    Set-Kv $DraftAppConfigName "experience:reading_level" "grade 6" "candidate"
    Set-Kv $DraftAppConfigName "experience:response_structure" "a one-sentence acknowledgement, then 2 to 3 short bullet points, then a clear next step" "candidate"
    Set-Kv $DraftAppConfigName "experience:prompt_asset" "response:v2" "candidate"
}

if (-not $SkipKnowledge) {
    # Retrieval scope is configuration, exactly like tone. The production filter
    # admits approved content only.
    #
    # Both filters also pin the industry. The corpus spans retail, healthcare,
    # financial services, and onboarding, and keyword ranking over so few
    # documents otherwise puts the onboarding module above the returns policy
    # for a returns question. Pinning the industry keeps the comparison honest:
    # the only difference between the live and proposed filters is the status
    # clause, so any change in the answer is attributable to approval status.
    Write-Host "==> Seeding the knowledge retrieval scope..."
    foreach ($label in @("baseline", "candidate")) {
        Set-Kv $AppConfigName "knowledge:enabled" "true" $label
        Set-Kv $AppConfigName "knowledge:index" $KnowledgeIndex $label
        Set-Kv $AppConfigName "knowledge:filter" "industry eq 'retail' and status eq 'approved'" $label
        Set-Kv $AppConfigName "knowledge:top_k" "3" $label
        Set-Kv $AppConfigName "knowledge:query_mode" "simple" $label
        Set-Kv $AppConfigName "knowledge:citation_style" "inline" $label
    }

    if ($DraftAppConfigName) {
        # A deliberately unsafe proposal. It widens the scope to include content
        # marked draft, which is exactly the kind of change the approval gate is
        # there to catch. The Knowledge tab shows both scopes side by side.
        Write-Host "==> Seeding a proposed (wider) retrieval scope into the draft store..."
        Set-Kv $DraftAppConfigName "knowledge:enabled" "true" "candidate"
        Set-Kv $DraftAppConfigName "knowledge:index" $KnowledgeIndex "candidate"
        Set-Kv $DraftAppConfigName "knowledge:filter" "industry eq 'retail' and (status eq 'approved' or status eq 'draft')" "candidate"
        Set-Kv $DraftAppConfigName "knowledge:top_k" "3" "candidate"
        Set-Kv $DraftAppConfigName "knowledge:query_mode" "simple" "candidate"
        Set-Kv $DraftAppConfigName "knowledge:citation_style" "inline" "candidate"
    }
}

Write-Host "Done."
