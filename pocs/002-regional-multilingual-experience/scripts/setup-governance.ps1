#Requires -Version 5.1
<#
.SYNOPSIS
    Adds the governance layer: a second App Configuration store for drafts, a Log
    Analytics workspace collecting App Configuration audit logs, and five Entra
    ID service principals holding different roles across the two stores. Writes
    ../roles.local.json and updates ../.env.

.DESCRIPTION
    Two stores rather than two labels, for the reason this proof of concept
    exists to examine: Azure role assignment conditions are available for blob
    storage and queue storage data actions, not for App Configuration, so a
    data-plane role cannot be narrowed to a label.

    That limit is sharper here than in proof of concept 001, because a market IS
    a label. The market owner persona created below therefore receives exactly
    the same roles as the global designer. It is not a mistake in this script;
    it is the honest consequence of the platform, and the app surfaces it rather
    than papering over it. Delegating one market to one team needs a compensating
    control: per-locale code ownership on the assets, a gatekeeper component, or
    a store per market cohort.

    App Configuration resource logs are NOT collected by default. Until the
    diagnostic setting below exists there is no record of who changed what, which
    makes this the most important step after the role assignments themselves.

.NOTES
    Client secrets are a proof-of-concept shortcut so one process can act as
    several identities. Production would use managed identity, workload identity
    federation, or user sign-in with on-behalf-of, so that no secret exists.

    Issuing a client secret REPLACES the previous one, so two personas must never
    share an app registration. The app checks for this and warns.

.EXAMPLE
    pwsh scripts/setup-governance.ps1 -ProductionStore regml4751-appcfg
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-poc-regional-multilingual",
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
if (-not $DraftStore) { $DraftStore = "$baseName-appcfg-draft" }
if (-not $WorkspaceName) { $WorkspaceName = "$baseName-logs" }
if (-not $SpPrefix) { $SpPrefix = "poc-regml-$baseName" }
# The Free tier allows one store per region per subscription, so a Free draft
# store must sit somewhere else. Any other SKU can share the region.
if (-not $DraftLocation) { $DraftLocation = if ($DraftSku -eq "Free") { "westus" } else { $Location } }

Write-Host "==> Checking Azure CLI sign-in..."
az account show 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { az login | Out-Null }
$tenantId = az account show --query tenantId -o tsv
$userId = az ad signed-in-user show --query id -o tsv

$prodId = az appconfig show --name $ProductionStore --resource-group $ResourceGroup --query id -o tsv
if (-not $prodId) { throw "Could not find the production store $ProductionStore in $ResourceGroup." }

function Grant-Role {
    param([string]$ObjectId, [string]$Role, [string]$Scope)
    $existing = az role assignment list --scope $Scope `
        --query "[?principalId=='$ObjectId' && roleDefinitionName=='$Role'] | [0].id" -o tsv
    if ($existing) { return }
    az role assignment create --assignee-object-id $ObjectId --assignee-principal-type ServicePrincipal `
        --role $Role --scope $Scope --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to assign '$Role' at scope $Scope." }
}

function New-PocServicePrincipal {
    param([string]$Name)
    # Filter by an exact display name. Azure CLI lookups that match by prefix
    # will silently return the wrong registration when one name is a prefix of
    # another, which is how an identity ends up acting as a different persona.
    $appId = az ad app list --filter "displayName eq '$Name'" --query "[0].appId" -o tsv
    if ($appId) {
        Write-Host "    Reusing existing app registration $Name"
    }
    else {
        $appId = az ad app create --display-name $Name --sign-in-audience AzureADMyOrg --query appId -o tsv
        if (-not $appId) { throw "Could not create the app registration $Name." }
    }

    $objectId = az ad sp list --filter "appId eq '$appId'" --query "[0].id" -o tsv
    if (-not $objectId) {
        foreach ($attempt in 1..6) {
            az ad sp create --id $appId --only-show-errors | Out-Null
            $objectId = az ad sp list --filter "appId eq '$appId'" --query "[0].id" -o tsv
            if ($objectId) { break }
            Start-Sleep -Seconds 5
        }
    }
    if (-not $objectId) { throw "The service principal for $Name did not appear." }

    $secret = az ad app credential reset --id $appId --display-name "poc-governance" --years 1 --query password -o tsv
    if (-not $secret) { throw "Could not issue a client secret for $Name." }
    return [pscustomobject]@{ Name = $Name; AppId = $appId; ObjectId = $objectId; Secret = $secret }
}

Write-Host "==> Creating the draft App Configuration store $DraftStore ($DraftSku in $DraftLocation)..."
az appconfig create --name $DraftStore --resource-group $ResourceGroup `
    --location $DraftLocation --sku $DraftSku --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not create the draft store $DraftStore." }
$draftId = az appconfig show --name $DraftStore --resource-group $ResourceGroup --query id -o tsv
$draftEndpoint = az appconfig show --name $DraftStore --resource-group $ResourceGroup --query endpoint -o tsv

Write-Host "==> Granting your account Data Owner on both stores..."
az role assignment create --assignee-object-id $userId --assignee-principal-type User `
    --role "App Configuration Data Owner" --scope $draftId --only-show-errors | Out-Null

Write-Host "==> Creating the Log Analytics workspace $WorkspaceName..."
az monitor log-analytics workspace create --resource-group $ResourceGroup `
    --workspace-name $WorkspaceName --location $Location --only-show-errors | Out-Null
$workspaceResourceId = az monitor log-analytics workspace show --resource-group $ResourceGroup `
    --workspace-name $WorkspaceName --query id -o tsv
$workspaceCustomerId = az monitor log-analytics workspace show --resource-group $ResourceGroup `
    --workspace-name $WorkspaceName --query customerId -o tsv

Write-Host "==> Routing App Configuration audit logs to the workspace..."
$logsFile = New-TemporaryFile
Set-Content -Path $logsFile.FullName -Value '[{"categoryGroup":"allLogs","enabled":true}]' -Encoding ascii
foreach ($target in @(@{ Id = $prodId; Name = "prod" }, @{ Id = $draftId; Name = "draft" })) {
    az monitor diagnostic-settings create --name "appcfg-audit-$($target.Name)" `
        --resource $target.Id --workspace $workspaceResourceId `
        --logs "@$($logsFile.FullName)" --only-show-errors 1>$null 2>$null
}
Remove-Item $logsFile.FullName -ErrorAction SilentlyContinue

Write-Host "==> Creating service principals and assigning roles..."

$viewer = New-PocServicePrincipal "$SpPrefix-viewer"
Grant-Role $viewer.ObjectId "App Configuration Data Reader" $prodId
Grant-Role $viewer.ObjectId "App Configuration Data Reader" $draftId

$designer = New-PocServicePrincipal "$SpPrefix-designer"
Grant-Role $designer.ObjectId "App Configuration Data Reader" $prodId
Grant-Role $designer.ObjectId "App Configuration Data Owner" $draftId

# Identical roles to the designer, deliberately. Azure has no way to say "only
# the de-DE label", and pretending otherwise would be the one dishonest thing
# this demonstration could do.
$marketOwner = New-PocServicePrincipal "$SpPrefix-marketowner"
Grant-Role $marketOwner.ObjectId "App Configuration Data Reader" $prodId
Grant-Role $marketOwner.ObjectId "App Configuration Data Owner" $draftId

$approver = New-PocServicePrincipal "$SpPrefix-approver"
Grant-Role $approver.ObjectId "App Configuration Data Owner" $prodId
Grant-Role $approver.ObjectId "App Configuration Data Owner" $draftId

# Least privilege: the customer-facing runtime reads live configuration only. A
# compromised or defective application cannot rewrite a market, cannot see an
# unpublished market layer, and cannot loosen a certification gate.
$appSp = New-PocServicePrincipal "$SpPrefix-runtime"
Grant-Role $appSp.ObjectId "App Configuration Data Reader" $prodId

Write-Host "==> Writing roles.local.json..."
$rolesPath = Join-Path (Split-Path $PSScriptRoot -Parent) "roles.local.json"
$roles = [ordered]@{
    tenantId = $tenantId
    personas = [ordered]@{
        viewer       = [ordered]@{ displayName = $viewer.Name;      clientId = $viewer.AppId;      clientSecret = $viewer.Secret }
        designer     = [ordered]@{ displayName = $designer.Name;    clientId = $designer.AppId;    clientSecret = $designer.Secret }
        market_owner = [ordered]@{ displayName = $marketOwner.Name; clientId = $marketOwner.AppId; clientSecret = $marketOwner.Secret }
        approver     = [ordered]@{ displayName = $approver.Name;    clientId = $approver.AppId;    clientSecret = $approver.Secret }
        app          = [ordered]@{ displayName = $appSp.Name;       clientId = $appSp.AppId;       clientSecret = $appSp.Secret }
    }
}
$roles | ConvertTo-Json -Depth 5 | Set-Content -Path $rolesPath -Encoding utf8

Write-Host "==> Updating .env..."
$envPath = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
$keep = @()
if (Test-Path $envPath) {
    $keep = Get-Content $envPath | Where-Object {
        $_ -notmatch '^AZURE_APPCONFIG_DRAFT_ENDPOINT=' -and `
        $_ -notmatch '^AZURE_LOG_ANALYTICS_WORKSPACE_ID=' -and `
        $_.Trim()
    }
}
$envContent = (($keep + @(
    "AZURE_APPCONFIG_DRAFT_ENDPOINT=$draftEndpoint",
    "AZURE_LOG_ANALYTICS_WORKSPACE_ID=$workspaceCustomerId"
)) -join "`n") + "`n"
[System.IO.File]::WriteAllText($envPath, $envContent, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "Done. Wrote $rolesPath (excluded by .gitignore)."
Write-Host "Role assignments can take up to 15 minutes to propagate."
Write-Host "Next: pwsh scripts/seed-config.ps1 -AppConfigName $ProductionStore -DraftAppConfigName $DraftStore"
