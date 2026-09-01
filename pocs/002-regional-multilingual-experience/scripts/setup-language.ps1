#Requires -Version 5.1
<#
.SYNOPSIS
    Adds the language-adherence guardrail: an Azure AI Language resource used to
    detect the language of a generated answer and compare it to the market's
    expected language.

.DESCRIPTION
    Optional, and the smallest script here. Without it the app reports the
    guardrail as unavailable and everything else still runs.

    It is worth running anyway, because it covers the failure this whole design
    invites. Models revert to the source language most often when the retrieved
    context is in that language, which is exactly the situation a multilingual
    knowledge base creates. A German customer receiving a fluent English answer
    is not a subtle degradation, and it does not happen every time, so no amount
    of prompt review catches it.

    What happens on a mismatch is configuration, not code:

      market:language_adherence = enforce   withhold the answer, hand off
      market:language_adherence = warn      answer, record the mismatch
      market:language_adherence = off       do not check

    The seeded configuration sets de-DE to enforce and everything else to warn,
    because the cost of an English answer differs by market.

.NOTES
    The F0 (free) tier includes a monthly allowance that a demonstration will not
    exhaust. Language detection is a generally available feature of Azure AI
    Language. All access uses Entra ID; no keys are written to disk.

.EXAMPLE
    pwsh scripts/setup-language.ps1 -ProductionStore regml4751-appcfg
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-poc-regional-multilingual",
    [Parameter(Mandatory = $true)][string]$ProductionStore,
    [string]$Location = "eastus",
    [ValidateSet("F0", "S")][string]$Sku = "F0",
    [string]$LanguageService
)

$ErrorActionPreference = "Stop"

$baseName = $ProductionStore -replace '-appcfg$', ''
if (-not $LanguageService) { $LanguageService = "$baseName-lang" }

Write-Host "==> Checking Azure CLI sign-in..."
az account show 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { az login | Out-Null }
$userId = az ad signed-in-user show --query id -o tsv

Write-Host "==> Creating the Azure AI Language resource $LanguageService ($Sku)..."
az cognitiveservices account create `
    --name $LanguageService `
    --resource-group $ResourceGroup `
    --location $Location `
    --kind TextAnalytics `
    --sku $Sku `
    --custom-domain $LanguageService `
    --yes --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw @"
Could not create the Azure AI Language resource with SKU '$Sku'.
A subscription may hold only one F0 resource of this kind. Options:
  -Sku S                        (pay as you go)
  -LanguageService <existing>   (reuse a resource you already have)
"@
}
$languageId = az cognitiveservices account show --name $LanguageService --resource-group $ResourceGroup --query id -o tsv
$languageEndpoint = az cognitiveservices account show --name $LanguageService --resource-group $ResourceGroup --query properties.endpoint -o tsv

Write-Host "==> Assigning Cognitive Services Language Reader to your account..."
$existing = az role assignment list --scope $languageId `
    --query "[?principalId=='$userId' && roleDefinitionName=='Cognitive Services Language Reader'] | [0].id" -o tsv
if (-not $existing) {
    az role assignment create --assignee-object-id $userId --assignee-principal-type User `
        --role "Cognitive Services Language Reader" --scope $languageId --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to assign 'Cognitive Services Language Reader' at scope $languageId." }
}

Write-Host "==> Updating .env..."
$envPath = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
$keep = @()
if (Test-Path $envPath) {
    $keep = Get-Content $envPath | Where-Object { $_ -notmatch '^AZURE_LANGUAGE_ENDPOINT=' -and $_.Trim() }
}
$envContent = (($keep + @("AZURE_LANGUAGE_ENDPOINT=$languageEndpoint")) -join "`n") + "`n"
[System.IO.File]::WriteAllText($envPath, $envContent, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "Done. Wrote AZURE_LANGUAGE_ENDPOINT to $envPath"
Write-Host "RBAC can take a minute to propagate. Restart the app to pick up the endpoint."
