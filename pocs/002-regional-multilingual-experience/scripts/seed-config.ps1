#Requires -Version 5.1
<#
.SYNOPSIS
    Seeds the global default layer and three sparse market layers into Azure App
    Configuration, and optionally mirrors them into the draft store.

.DESCRIPTION
    The shape of this script is the point of the design, so read it as
    documentation rather than as plumbing.

    The 'baseline' layer carries every key. Each market layer carries only the
    keys that market actually changes. en-US overrides four values and inherits
    the rest; de-DE overrides ten because a regulated market in another language
    genuinely differs in more places. Adding a fourth market means adding a
    handful of lines here and the content to go with it, not a branch in code.

    A 'de-DE-candidate' layer is seeded with a single key so the third layer of
    the resolution chain, the experiment layer, is visible in the app.

.NOTES
    Uses --auth-mode login so no access key is required or written to disk.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AppConfigName,
    [string]$DraftAppConfigName,
    [ValidateSet("login", "key")][string]$AuthMode = "login",
    [switch]$SkipKnowledge
)

$ErrorActionPreference = "Stop"

function Set-Kv {
    param([string]$Store, [string]$Key, [string]$Value, [string]$Label)
    az appconfig kv set --name $Store --key $Key --value $Value `
        --label $Label --auth-mode $AuthMode --yes | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to set $Key on label '$Label' in $Store." }
}

function Set-StoreLayers {
    param([string]$Store)

    Write-Host "==> [$Store] Seeding the 'baseline' layer (global defaults, every key)..."
    Set-Kv $Store "experience:persona" "a Contoso customer support specialist" "baseline"
    Set-Kv $Store "experience:tone" "warm and professional" "baseline"
    Set-Kv $Store "experience:verbosity" "concise but complete" "baseline"
    Set-Kv $Store "experience:reading_level" "grade 8" "baseline"
    Set-Kv $Store "experience:response_structure" "a one-sentence acknowledgement, then 2 to 3 short bullet points, then a clear next step" "baseline"
    Set-Kv $Store "experience:formality" "neutral" "baseline"
    Set-Kv $Store "experience:prompt_asset" "response:v3" "baseline"

    Set-Kv $Store "market:locale" "global" "baseline"
    Set-Kv $Store "market:language" "en" "baseline"
    Set-Kv $Store "market:jurisdiction" "global" "baseline"
    Set-Kv $Store "market:disclosure_set" "none" "baseline"
    Set-Kv $Store "market:glossary_asset" "none" "baseline"
    Set-Kv $Store "market:language_adherence" "warn" "baseline"
    Set-Kv $Store "market:escalation_path" "global-support-queue" "baseline"

    if (-not $SkipKnowledge) {
        Set-Kv $Store "knowledge:enabled" "true" "baseline"
        Set-Kv $Store "knowledge:index" "kb-en-current" "baseline"
        Set-Kv $Store "knowledge:filter" "status eq 'approved'" "baseline"
        Set-Kv $Store "knowledge:top_k" "3" "baseline"
        Set-Kv $Store "knowledge:query_mode" "simple" "baseline"
        Set-Kv $Store "knowledge:citation_style" "inline" "baseline"
        Set-Kv $Store "knowledge:translation_gate" "certified" "baseline"
    }

    # en-US is the source market. It differs from the global default in almost
    # nothing, which is what a sparse layer is supposed to look like.
    Write-Host "==> [$Store] Seeding the 'en-US' layer (4 overrides)..."
    Set-Kv $Store "market:locale" "en-US" "en-US"
    Set-Kv $Store "market:jurisdiction" "US" "en-US"
    Set-Kv $Store "market:escalation_path" "us-support-queue" "en-US"
    if (-not $SkipKnowledge) {
        Set-Kv $Store "knowledge:filter" "status eq 'approved' and language eq 'en' and (jurisdiction eq 'US' or jurisdiction eq 'global')" "en-US"
    }

    # es-MX marks formality where English does not, needs its own index and
    # glossary, and accepts in-market review rather than formal certification
    # because the risk profile is different.
    Write-Host "==> [$Store] Seeding the 'es-MX' layer..."
    Set-Kv $Store "market:locale" "es-MX" "es-MX"
    Set-Kv $Store "market:language" "es" "es-MX"
    Set-Kv $Store "market:jurisdiction" "MX" "es-MX"
    Set-Kv $Store "market:disclosure_set" "mx-ai-disclosure:v1" "es-MX"
    Set-Kv $Store "market:glossary_asset" "glossary-es:v1" "es-MX"
    Set-Kv $Store "market:escalation_path" "mx-support-queue" "es-MX"
    Set-Kv $Store "experience:formality" "formal (usted)" "es-MX"
    if (-not $SkipKnowledge) {
        Set-Kv $Store "knowledge:index" "kb-es-current" "es-MX"
        Set-Kv $Store "knowledge:filter" "status eq 'approved' and language eq 'es' and (jurisdiction eq 'MX' or jurisdiction eq 'global')" "es-MX"
        Set-Kv $Store "knowledge:translation_gate" "reviewed" "es-MX"
    }

    # de-DE is the regulated market. It requires certified content, requires a
    # notice, and enforces rather than warns on a language mismatch.
    Write-Host "==> [$Store] Seeding the 'de-DE' layer..."
    Set-Kv $Store "market:locale" "de-DE" "de-DE"
    Set-Kv $Store "market:language" "de" "de-DE"
    Set-Kv $Store "market:jurisdiction" "EU-DE" "de-DE"
    Set-Kv $Store "market:disclosure_set" "eu-ai-disclosure:v1" "de-DE"
    Set-Kv $Store "market:glossary_asset" "glossary-de:v1" "de-DE"
    Set-Kv $Store "market:language_adherence" "enforce" "de-DE"
    Set-Kv $Store "market:escalation_path" "de-support-queue" "de-DE"
    Set-Kv $Store "experience:formality" "formal (Sie)" "de-DE"
    if (-not $SkipKnowledge) {
        Set-Kv $Store "knowledge:index" "kb-de-current" "de-DE"
        Set-Kv $Store "knowledge:filter" "status eq 'approved' and language eq 'de' and (jurisdiction eq 'EU-DE' or jurisdiction eq 'global')" "de-DE"
        Set-Kv $Store "knowledge:translation_gate" "certified" "de-DE"
    }

    # The third layer. One key is enough to show that an experiment overrides a
    # market the same way a market overrides the global default.
    Write-Host "==> [$Store] Seeding the 'de-DE-candidate' experiment layer (1 override)..."
    Set-Kv $Store "experience:tone" "warm, direct, and reassuring" "de-DE-candidate"
}

Write-Host "==> Seeding production store $AppConfigName..."
Set-StoreLayers $AppConfigName

if ($DraftAppConfigName) {
    Write-Host "==> Seeding draft store $DraftAppConfigName..."
    Set-StoreLayers $DraftAppConfigName
}
else {
    Write-Host "==> No -DraftAppConfigName supplied, so only the production store was seeded."
}

Write-Host ""
Write-Host "Done."
Write-Host "Layers seeded: baseline, en-US, es-MX, de-DE, de-DE-candidate."
Write-Host "Next: pwsh scripts/setup-knowledge.ps1 -ProductionStore $AppConfigName"
