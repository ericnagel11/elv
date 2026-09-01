#Requires -Version 5.1
<#
.SYNOPSIS
    Adds the RBAC governance layer to the config-driven responses PoC: a draft
    App Configuration store, a Log Analytics workspace with audit diagnostics,
    and four Microsoft Entra service principals holding different Azure
    built-in roles.

.DESCRIPTION
    Run this AFTER scripts/setup.ps1. It is additive: the existing production
    store, the Azure OpenAI account, and the existing .env values are preserved.

    Roles created, every one scoped to a single store and never to the
    subscription:

      <prefix>-viewer     Data Reader on production and draft
      <prefix>-designer   Data Owner on draft, Data Reader on production
      <prefix>-approver   Data Owner on production and draft
      <prefix>-runtime    Data Reader on production only

    Azure does not support ABAC role-assignment conditions for App
    Configuration, so a role cannot be limited to one label inside a store.
    Two stores are therefore used, which matches Microsoft guidance to use a
    separate store for each environment that needs different permissions.

.NOTES
    Requires the Azure CLI and permission to create Entra app registrations,
    for example the Application Developer role.

    Service principal secrets are written to roles.local.json, which is
    gitignored. This is a proof-of-concept shortcut so one process can act as
    several identities; production would use managed identity or user sign-in.
    Run scripts/teardown.ps1 to delete the service principals afterwards.

.EXAMPLE
    pwsh scripts/setup-governance.ps1 -ProductionStore cfgresp4751-appcfg
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-poc-config-responses",
    [Parameter(Mandatory = $true)][string]$ProductionStore,
    [string]$DraftStore,
    [string]$Location = "eastus",
    [ValidateSet("Developer", "Standard", "Premium", "Free")][string]$DraftSku = "Developer",
    [string]$DraftLocation,
    [string]$WorkspaceName,
    [string]$SpPrefix
)

$ErrorActionPreference = "Stop"

$baseName = $ProductionStore -replace '-appcfg$', ''
if (-not $DraftStore) { $DraftStore = "$baseName-draft-appcfg" }
if (-not $WorkspaceName) { $WorkspaceName = "$baseName-logs" }
if (-not $SpPrefix) { $SpPrefix = "sp-$baseName" }
# The Free tier allows only one store per subscription per region, so a Free
# draft store must sit in a different region.
if (-not $DraftLocation) { $DraftLocation = $Location }

Write-Host "==> Checking Azure CLI sign-in..."
az account show 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { az login | Out-Null }
$tenantId = az account show --query tenantId -o tsv

function Grant-Role {
    param([string]$ObjectId, [string]$Role, [string]$Scope)
    # Querying by scope avoids assignee-resolution failures for a principal that
    # was only just created, and keeps re-runs idempotent.
    $existing = az role assignment list --scope $Scope `
        --query "[?principalId=='$ObjectId' && roleDefinitionName=='$Role'] | [0].id" -o tsv
    if ($existing) { return }
    az role assignment create `
        --assignee-object-id $ObjectId `
        --assignee-principal-type ServicePrincipal `
        --role $Role --scope $Scope --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to assign '$Role' at scope $Scope." }
}

function New-PocServicePrincipal {
    param([string]$Name)
    # An OData filter matches the display name exactly. '--display-name' does a
    # prefix match, which would let one persona reuse another persona's app
    # registration when one name is a prefix of the other.
    $appId = az ad app list --filter "displayName eq '$Name'" --query "[0].appId" -o tsv
    if ($appId) {
        Write-Host "    Reusing existing app registration $Name"
    }
    else {
        $appId = az ad app create --display-name $Name --sign-in-audience AzureADMyOrg --query appId -o tsv
    }
    if (-not $appId) {
        throw "Could not create the app registration '$Name'. Your account may lack Entra permissions (Application Developer)."
    }

    # 'az ad sp list' returns an empty result when the principal is absent.
    # 'az ad sp show' would write to stderr, which PowerShell turns into a
    # terminating error while ErrorActionPreference is Stop.
    $objectId = az ad sp list --filter "appId eq '$appId'" --query "[0].id" -o tsv
    if (-not $objectId) {
        # Directory replication can lag behind app registration creation.
        foreach ($attempt in 1..6) {
            az ad sp create --id $appId --only-show-errors | Out-Null
            $objectId = az ad sp list --filter "appId eq '$appId'" --query "[0].id" -o tsv
            if ($objectId) { break }
            Start-Sleep -Seconds 5
        }
    }
    if (-not $objectId) { throw "Could not create a service principal for '$Name'." }

    $secret = az ad app credential reset --id $appId --display-name "poc-governance" --years 1 --query password -o tsv
    if (-not $secret) { throw "Could not create a client secret for '$Name'." }
    return [pscustomobject]@{ Name = $Name; AppId = $appId; ObjectId = $objectId; Secret = $secret }
}

# --- Draft store -----------------------------------------------------------
Write-Host "==> Creating the draft App Configuration store $DraftStore ($DraftSku, $DraftLocation)..."
az appconfig create --name $DraftStore --resource-group $ResourceGroup `
    --location $DraftLocation --sku $DraftSku --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw @"
Could not create the draft store with SKU '$DraftSku'.
The Free tier allows only one store per subscription per region. Options:
  -DraftSku Standard                       (if Developer is unavailable in your CLI or region)
  -DraftSku Free -DraftLocation westus2    (a second Free store in a different region)
"@
}

$prodId = az appconfig show --name $ProductionStore --resource-group $ResourceGroup --query id -o tsv
$prodEndpoint = az appconfig show --name $ProductionStore --resource-group $ResourceGroup --query endpoint -o tsv
$draftId = az appconfig show --name $DraftStore --resource-group $ResourceGroup --query id -o tsv
$draftEndpoint = az appconfig show --name $DraftStore --resource-group $ResourceGroup --query endpoint -o tsv

# Let the operator seed and inspect the draft store from the CLI.
Write-Host "==> Granting your account Data Owner on the draft store..."
$userId = az ad signed-in-user show --query id -o tsv
az role assignment create --assignee-object-id $userId --assignee-principal-type User `
    --role "App Configuration Data Owner" --scope $draftId --only-show-errors | Out-Null

# --- Audit trail -----------------------------------------------------------
Write-Host "==> Creating the Log Analytics workspace $WorkspaceName..."
az monitor log-analytics workspace create --resource-group $ResourceGroup `
    --workspace-name $WorkspaceName --location $Location --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not create the Log Analytics workspace. Try: az extension add --name log-analytics" }
$workspaceResourceId = az monitor log-analytics workspace show --resource-group $ResourceGroup `
    --workspace-name $WorkspaceName --query id -o tsv
$workspaceCustomerId = az monitor log-analytics workspace show --resource-group $ResourceGroup `
    --workspace-name $WorkspaceName --query customerId -o tsv

Write-Host "==> Enabling audit diagnostics on both stores..."
$logsFile = New-TemporaryFile
Set-Content -Path $logsFile.FullName -Value '[{"categoryGroup":"allLogs","enabled":true}]' -Encoding ascii
foreach ($target in @(@{ Id = $prodId; Name = "prod" }, @{ Id = $draftId; Name = "draft" })) {
    az monitor diagnostic-settings create --name "appcfg-audit-$($target.Name)" `
        --resource $target.Id --workspace $workspaceResourceId `
        --logs "@$($logsFile.FullName)" --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warning "Could not enable diagnostics on the $($target.Name) store." }
}
Remove-Item $logsFile.FullName -ErrorAction SilentlyContinue

# --- Identities and role assignments ---------------------------------------
Write-Host "==> Creating four service principals and assigning roles..."

$viewer = New-PocServicePrincipal "$SpPrefix-viewer"
Grant-Role $viewer.ObjectId "App Configuration Data Reader" $prodId
Grant-Role $viewer.ObjectId "App Configuration Data Reader" $draftId

$designer = New-PocServicePrincipal "$SpPrefix-designer"
Grant-Role $designer.ObjectId "App Configuration Data Reader" $prodId
Grant-Role $designer.ObjectId "App Configuration Data Owner" $draftId

$approver = New-PocServicePrincipal "$SpPrefix-approver"
Grant-Role $approver.ObjectId "App Configuration Data Owner" $prodId
Grant-Role $approver.ObjectId "App Configuration Data Owner" $draftId

# Least privilege: the customer-facing runtime reads the live experience only.
# Named 'runtime' rather than 'app' so no persona name is a prefix of another.
$appSp = New-PocServicePrincipal "$SpPrefix-runtime"
Grant-Role $appSp.ObjectId "App Configuration Data Reader" $prodId

$rolesPath = Join-Path (Split-Path $PSScriptRoot -Parent) "roles.local.json"
$roles = [ordered]@{
    tenantId = $tenantId
    personas = [ordered]@{
        viewer   = [ordered]@{ displayName = $viewer.Name;   clientId = $viewer.AppId;   clientSecret = $viewer.Secret }
        designer = [ordered]@{ displayName = $designer.Name; clientId = $designer.AppId; clientSecret = $designer.Secret }
        approver = [ordered]@{ displayName = $approver.Name; clientId = $approver.AppId; clientSecret = $approver.Secret }
        app      = [ordered]@{ displayName = $appSp.Name;    clientId = $appSp.AppId;    clientSecret = $appSp.Secret }
    }
}
$roles | ConvertTo-Json -Depth 5 | Set-Content -Path $rolesPath -Encoding utf8
Write-Host "    Wrote $rolesPath (gitignored; contains client secrets)"

# --- Update .env -----------------------------------------------------------
Write-Host "==> Updating .env..."
$envPath = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
$keep = @()
if (Test-Path $envPath) {
    $keep = Get-Content $envPath | Where-Object {
        $_ -notmatch '^AZURE_APPCONFIG_DRAFT_ENDPOINT=' -and $_ -notmatch '^AZURE_LOG_ANALYTICS_WORKSPACE_ID=' -and $_.Trim()
    }
}
$envContent = (($keep + @(
    "AZURE_APPCONFIG_DRAFT_ENDPOINT=$draftEndpoint",
    "AZURE_LOG_ANALYTICS_WORKSPACE_ID=$workspaceCustomerId"
)) -join "`n") + "`n"
[System.IO.File]::WriteAllText($envPath, $envContent, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "Governance layer ready."
Write-Host "  Production store : $ProductionStore"
Write-Host "  Draft store      : $DraftStore ($DraftSku)"
Write-Host "  Workspace        : $WorkspaceName"
Write-Host ""
Write-Host "Role assignments can take up to 15 minutes to propagate. A 403 before then is expected."
Write-Host "Next: pwsh scripts/seed-config.ps1 -AppConfigName $ProductionStore -DraftAppConfigName $DraftStore"
Write-Host "Then: streamlit run app.py"
