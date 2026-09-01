#Requires -Version 5.1
<#
.SYNOPSIS
    Removes the proof-of-concept resources and the Entra service principals
    created by setup-governance.ps1.

.DESCRIPTION
    Deleting the resource group alone is not enough. The four app
    registrations live in Microsoft Entra ID, outside the resource group, and
    would remain in the tenant. This script removes both.

    You are prompted before anything is deleted. Use -Force to skip the prompt.

.EXAMPLE
    pwsh scripts/teardown.ps1
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-poc-config-responses",
    [switch]$KeepResourceGroup,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

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

Write-Host "This will delete:"
if (-not $KeepResourceGroup) { Write-Host "  - Resource group: $ResourceGroup (all resources inside it)" }
if ($names) { $names | ForEach-Object { Write-Host "  - Entra app registration: $_" } }
else { Write-Host "  - No service principals found in roles.local.json" }
Write-Host ""

if (-not $Force) {
    $answer = Read-Host "Type 'delete' to continue"
    if ($answer -ne "delete") { Write-Host "Cancelled."; return }
}

foreach ($i in 0..([Math]::Max($appIds.Count - 1, -1))) {
    if ($appIds.Count -eq 0) { break }
    Write-Host "==> Deleting app registration $($names[$i])..."
    # Not redirecting stderr: with ErrorActionPreference set to Stop, a redirect
    # would turn Azure CLI output into a terminating error.
    az ad app delete --id $appIds[$i] --only-show-errors
    if ($LASTEXITCODE -ne 0) { Write-Warning "Could not delete $($names[$i]). Remove it manually in Microsoft Entra ID." }
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
Write-Host "Teardown started. Resource group deletion continues in the background."
Write-Host "Verify no identities remain:  az ad app list --display-name sp- --query '[].displayName' -o tsv"
