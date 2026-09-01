#Requires -Version 5.1
<#
.SYNOPSIS
    Provisions the minimal Azure resources for the config-driven responses PoC:
    a resource group, an Azure App Configuration store (Free), and an Azure
    OpenAI account with one chat model deployment. Assigns Entra ID (RBAC) roles
    to the signed-in user and writes ../.env.

.NOTES
    Requires the Azure CLI (az) and an Azure subscription where you can create
    Azure OpenAI. All access uses Entra ID; no keys are written to disk.
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId,
    [string]$Location = "eastus",
    [string]$ResourceGroup = "rg-poc-config-responses",
    [string]$BaseName = "cfgresp$(Get-Random -Maximum 9999)",
    [string]$Model = "gpt-5-mini",
    [string]$ModelVersion = "",
    [string]$ModelSku = "GlobalStandard",
    [string]$ApiVersion = "2024-10-21",
    [string]$ExpirationDate = (Get-Date).AddDays(14).ToString("yyyy-MM-dd")
)

$ErrorActionPreference = "Stop"

Write-Host "==> Checking Azure CLI sign-in..."
az account show 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { az login | Out-Null }
if ($SubscriptionId) { az account set --subscription $SubscriptionId }
$sub = az account show --query id -o tsv
$userUpn = az account show --query user.name -o tsv
Write-Host "Subscription: $sub"

Write-Host "==> Ensuring required resource providers are registered..."
foreach ($ns in @("Microsoft.AppConfiguration", "Microsoft.CognitiveServices")) {
    $state = az provider show --namespace $ns --query registrationState -o tsv 2>$null
    if ($state -ne "Registered") {
        Write-Host "    Registering $ns (this can take a few minutes)..."
        az provider register --namespace $ns --wait | Out-Null
    }
}

$appConfigName = "$BaseName-appcfg"
$openAiName = "$BaseName-aoai"

$tags = @(
    "Application=config-driven-responses",
    "Environment=poc",
    "Owner=$userUpn",
    "DataClassification=synthetic",
    "ManagedBy=poc",
    "ExpirationDate=$ExpirationDate"
)

Write-Host "==> Creating resource group $ResourceGroup..."
az group create --name $ResourceGroup --location $Location --tags $tags | Out-Null

Write-Host "==> Creating App Configuration store $appConfigName (Free)..."
az appconfig create --name $appConfigName --resource-group $ResourceGroup --location $Location --sku Free | Out-Null
$appConfigId = az appconfig show --name $appConfigName --resource-group $ResourceGroup --query id -o tsv
$appConfigEndpoint = az appconfig show --name $appConfigName --resource-group $ResourceGroup --query endpoint -o tsv

Write-Host "==> Creating Azure OpenAI account $openAiName..."
az cognitiveservices account create `
    --name $openAiName `
    --resource-group $ResourceGroup `
    --location $Location `
    --kind OpenAI `
    --sku S0 `
    --custom-domain $openAiName | Out-Null
$openAiId = az cognitiveservices account show --name $openAiName --resource-group $ResourceGroup --query id -o tsv
$openAiEndpoint = az cognitiveservices account show --name $openAiName --resource-group $ResourceGroup --query properties.endpoint -o tsv

if (-not $ModelVersion) {
    Write-Host "==> Resolving newest available version for $Model..."
    $ModelVersion = az cognitiveservices account list-models `
        --name $openAiName --resource-group $ResourceGroup `
        --query "sort_by([?name=='$Model'], &version)[-1].version" -o tsv
    if (-not $ModelVersion) { throw "Model '$Model' is not offered in $Location for this account. Try a different -Model or -Location." }
}

Write-Host "==> Deploying model $Model ($ModelVersion), SKU $ModelSku..."
az cognitiveservices account deployment create `
    --name $openAiName `
    --resource-group $ResourceGroup `
    --deployment-name $Model `
    --model-name $Model `
    --model-version $ModelVersion `
    --model-format OpenAI `
    --sku-name $ModelSku `
    --sku-capacity 10 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Model deployment failed for $Model ($ModelVersion), SKU $ModelSku. Check model availability and quota in $Location, then re-run." }

Write-Host "==> Assigning RBAC roles to $userUpn..."
$userId = az ad signed-in-user show --query id -o tsv
az role assignment create --assignee-object-id $userId --assignee-principal-type User `
    --role "App Configuration Data Owner" --scope $appConfigId | Out-Null
az role assignment create --assignee-object-id $userId --assignee-principal-type User `
    --role "Cognitive Services OpenAI User" --scope $openAiId | Out-Null

Write-Host "==> Writing .env..."
$envPath = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
$envContent = @"
AZURE_APPCONFIG_ENDPOINT=$appConfigEndpoint
AZURE_OPENAI_ENDPOINT=$openAiEndpoint
AZURE_OPENAI_DEPLOYMENT=$Model
AZURE_OPENAI_API_VERSION=$ApiVersion
"@
# Write UTF-8 without a BOM so python-dotenv reads the first key correctly.
[System.IO.File]::WriteAllText($envPath, $envContent, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "Done. Wrote $envPath"
Write-Host "RBAC can take a minute to propagate."
Write-Host "Next: pwsh scripts/seed-config.ps1 -AppConfigName $appConfigName"
