#Requires -Version 5.1
<#
.SYNOPSIS
    Removes everything this proof of concept created: the app registrations
    listed in roles.local.json, the resource group, and the local roles file.

.DESCRIPTION
    App registrations live in Microsoft Entra ID, not in the resource group, so
    deleting the group alone leaves five orphaned registrations behind. They are
    deleted first, from the record this proof of concept wrote, which is why
    roles.local.json is removed last.

.EXAMPLE
    pwsh scripts/teardown.ps1

.EXAMPLE
    pwsh scripts/teardown.ps1 -KeepResourceGroup
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-poc-regional-multilingual",
    [switch]$KeepResourceGroup,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Write-Host "==> Checking Azure CLI sign-in..."
az account show 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { az login | Out-Null }
$sub = az account show --query id -o tsv

$rolesPath = Join-Path (Split-Path $PSScriptRoot -Parent) "roles.local.json"
$appIds = @()
$names = @()
if (Test-Path $rolesPath) {
    $roles = Get-Content $rolesPath -Raw | ConvertFrom-Json
    foreach ($persona in $roles.personas.PSObject.Properties) {
        $appIds += $persona.Value.clientId
        $names += $persona.Value.displayName
    }
}

Write-Host ""
Write-Host "About to delete from subscription $sub"
if (-not $KeepResourceGroup) { Write-Host "  resource group   $ResourceGroup" }
foreach ($name in $names) { Write-Host "  app registration $name" }
Write-Host ""

if (-not $Force) {
    $answer = Read-Host "Type the resource group name to confirm"
    if ($answer -ne $ResourceGroup) {
        Write-Host "Nothing was deleted."
        return
    }
}

for ($i = 0; $i -lt $appIds.Count; $i++) {
    Write-Host "==> Deleting app registration $($names[$i])..."
    az ad app delete --id $appIds[$i] --only-show-errors 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Warning "Could not delete $($names[$i]). Delete it by hand in Microsoft Entra ID." }
}

if (-not $KeepResourceGroup) {
    Write-Host "==> Deleting resource group $ResourceGroup..."
    az group delete --name $ResourceGroup --yes --no-wait
}

if (Test-Path $rolesPath) {
    Remove-Item $rolesPath
    Write-Host "==> Removed roles.local.json"
}

Write-Host ""
Write-Host "Teardown started. The resource group deletes in the background."
Write-Host "Azure OpenAI and Azure AI Language accounts are soft-deleted and hold their name for 48 hours."
Write-Host "Your local .env is untouched. Delete it by hand if you want a clean slate."
