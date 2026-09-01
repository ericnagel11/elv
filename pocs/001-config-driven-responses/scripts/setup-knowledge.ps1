#Requires -Version 5.1
<#
.SYNOPSIS
    Adds the configurable-knowledge layer to the config-driven responses PoC: a
    storage account holding governed content, an Azure AI Search index, and an
    indexer that keeps the index current without any application code.

.DESCRIPTION
    Run this AFTER scripts/setup.ps1 (and ideally after setup-governance.ps1, so
    the persona service principals exist and can be granted query access).

    What it creates:

      <prefix>kb          storage account, container "knowledge"
      <prefix>-search     Azure AI Search service
      kb-v1               the search index
      kb-current          an index alias, which is what the app queries
      kb-blobs            the indexer data source, with a soft-delete policy
      kb-indexer          the indexer, on an hourly schedule

    Deliberate choices worth knowing about:

    1. The deletion detection policy is configured on the FIRST indexer run.
       Azure AI Search does not detect deletions automatically, and a policy
       added later will not retroactively remove documents that were deleted
       before it existed. The only remedy then is to build a new index.

    2. Queries go to the alias kb-current, never to kb-v1 directly. An indexer
       cannot target an alias, so the indexer writes to the concrete index and
       the alias is repointed to publish or roll back a whole knowledge set.

    3. There is no skillset, so no chunking and no vectors. That keeps the proof
       of concept cheap and is enough to show that content and retrieval scope
       are configuration. Vectorization is the documented scaling path.

.NOTES
    Managed identity requires the Basic tier or higher. On the Free tier the
    indexer must authenticate to storage with an account key, which the script
    will do while warning about it. Semantic ranking also requires Basic or
    higher; the app falls back to keyword ranking and says so.

    Free tier: one free search service per subscription.

.EXAMPLE
    pwsh scripts/setup-knowledge.ps1 -ProductionStore cfgresp4751-appcfg

.EXAMPLE
    pwsh scripts/setup-knowledge.ps1 -ProductionStore cfgresp4751-appcfg -SearchSku Basic
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-poc-config-responses",
    [Parameter(Mandatory = $true)][string]$ProductionStore,
    [string]$Location = "eastus",
    [ValidateSet("Free", "Basic", "Standard")][string]$SearchSku = "Free",
    [string]$StorageAccount,
    [string]$SearchService,
    [string]$Container = "knowledge",
    [string]$IndexName = "kb-v1",
    [string]$AliasName = "kb-current",
    # Must be a version that exposes /aliases. 2024-07-01 does not: it rejects
    # the call with "The version indicated by the api-version query string
    # parameter does not exist", even though /indexes works on that version.
    [string]$SearchApiVersion = "2026-04-01"
)

$ErrorActionPreference = "Stop"

$baseName = $ProductionStore -replace '-appcfg$', ''
if (-not $StorageAccount) { $StorageAccount = (($baseName -replace '[^a-zA-Z0-9]', '').ToLower() + "kb") }
if ($StorageAccount.Length -gt 24) { $StorageAccount = $StorageAccount.Substring(0, 24) }
if (-not $SearchService) { $SearchService = "$baseName-search" }

$root = Split-Path $PSScriptRoot -Parent
$knowledgeDir = Join-Path $root "knowledge"
$manifestPath = Join-Path $knowledgeDir "manifest.json"
if (-not (Test-Path $manifestPath)) { throw "Missing $manifestPath." }

Write-Host "==> Checking Azure CLI sign-in..."
az account show 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { az login | Out-Null }
$subscriptionId = az account show --query id -o tsv
$userId = az ad signed-in-user show --query id -o tsv

function Grant-Role {
    param([string]$ObjectId, [string]$PrincipalType, [string]$Role, [string]$Scope)
    $existing = az role assignment list --scope $Scope `
        --query "[?principalId=='$ObjectId' && roleDefinitionName=='$Role'] | [0].id" -o tsv
    if ($existing) { return }
    az role assignment create --assignee-object-id $ObjectId --assignee-principal-type $PrincipalType `
        --role $Role --scope $Scope --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to assign '$Role' at scope $Scope." }
}

function Invoke-SearchApi {
    param(
        [ValidateSet("GET", "PUT", "POST", "DELETE")][string]$Method,
        [string]$Path,
        [object]$Body,
        [int]$RetrySeconds = 0
    )
    $uri = "https://$SearchService.search.windows.net$Path"
    # Use a literal containment test, not -like: in a wildcard pattern "?" means
    # "any single character", so "*?*" matches every non-empty path and would
    # append "&api-version=..." instead of "?api-version=...". Windows PowerShell
    # then hands that unescaped "&" to cmd.exe when it launches az.cmd, which
    # truncates the command line and drops --resource.
    $uri += ($(if ($Path.Contains("?")) { "&" } else { "?" }) + "api-version=$SearchApiVersion")

    $arguments = @("rest", "--method", $Method.ToLower(), "--uri", $uri,
        "--resource", "https://search.azure.com",
        "--headers", "Content-Type=application/json", "--only-show-errors")

    $bodyFile = $null
    if ($null -ne $Body) {
        $bodyFile = [System.IO.Path]::GetTempFileName()
        $json = if ($Body -is [string]) { $Body } else { $Body | ConvertTo-Json -Depth 12 }
        [System.IO.File]::WriteAllText($bodyFile, $json, (New-Object System.Text.UTF8Encoding($false)))
        $arguments += @("--body", "@$bodyFile")
    }
    $errorFile = [System.IO.Path]::GetTempFileName()

    try {
        $deadline = (Get-Date).AddSeconds($RetrySeconds)
        while ($true) {
            # Send stderr to a file rather than merging it with 2>&1. Merging turns
            # any Azure CLI warning into a terminating error while
            # ErrorActionPreference is Stop, and it would also corrupt the JSON.
            $previous = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            $output = & az @arguments 2>$errorFile
            $exitCode = $LASTEXITCODE
            $ErrorActionPreference = $previous

            if ($exitCode -eq 0) { return ($output | Out-String) }

            $detail = (Get-Content $errorFile -Raw -ErrorAction SilentlyContinue)
            $isPropagation = $detail -match "403" -or $detail -match "Forbidden" -or $detail -match "AuthorizationPermissionMismatch"
            # A search service that was created moments ago often has no DNS
            # record yet, so the first data-plane call can fail to resolve.
            $isDns = $detail -match "NameResolutionError" -or $detail -match "getaddrinfo failed" -or $detail -match "Failed to resolve"
            if (($isPropagation -or $isDns) -and (Get-Date) -lt $deadline) {
                $reason = if ($isDns) { "the endpoint to appear in DNS" } else { "the role assignment to propagate" }
                Write-Host "    Waiting for $reason..."
                Start-Sleep -Seconds 15
                continue
            }
            throw "Search API $Method $Path failed: $detail"
        }
    }
    finally {
        if ($bodyFile) { Remove-Item $bodyFile -ErrorAction SilentlyContinue }
        Remove-Item $errorFile -ErrorAction SilentlyContinue
    }
}

# --- Storage ---------------------------------------------------------------
Write-Host "==> Creating the storage account $StorageAccount..."
az storage account create --name $StorageAccount --resource-group $ResourceGroup `
    --location $Location --sku Standard_LRS --kind StorageV2 `
    --min-tls-version TLS1_2 --allow-blob-public-access false --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not create the storage account $StorageAccount." }
$storageId = az storage account show --name $StorageAccount --resource-group $ResourceGroup --query id -o tsv

Write-Host "==> Granting your account Storage Blob Data Contributor..."
Grant-Role $userId "User" "Storage Blob Data Contributor" $storageId

Write-Host "==> Creating the container $Container..."
$containerCreated = $false
foreach ($attempt in 1..12) {
    az storage container create --name $Container --account-name $StorageAccount `
        --auth-mode login --only-show-errors 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) { $containerCreated = $true; break }
    Write-Host "    Waiting for the role assignment to propagate..."
    Start-Sleep -Seconds 15
}
if (-not $containerCreated) { throw "Could not create the container. The role assignment may not have propagated yet." }

# --- Content ---------------------------------------------------------------
# Metadata travels with the content, not with the code. Moving a document from
# draft to approved is a metadata change made by a content steward.
Write-Host "==> Uploading governed content with metadata..."
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
foreach ($document in $manifest.documents) {
    $path = Join-Path $knowledgeDir $document.file
    if (-not (Test-Path $path)) { throw "Manifest references a missing file: $($document.file)" }

    $metadata = @()
    foreach ($property in $document.PSObject.Properties) {
        if ($property.Name -eq "file") { continue }
        $metadata += "$($property.Name)=$($property.Value)"
    }

    az storage blob upload --account-name $StorageAccount --container-name $Container `
        --name $document.file --file $path --content-type "text/plain" `
        --metadata @metadata --overwrite --auth-mode login --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not upload $($document.file)." }
    Write-Host "    $($document.file)  [status=$($document.status), industry=$($document.industry)]"
}

# --- Search service --------------------------------------------------------
Write-Host "==> Creating the search service $SearchService ($SearchSku)..."
az search service create --name $SearchService --resource-group $ResourceGroup `
    --location $Location --sku $SearchSku --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw @"
Could not create the search service with SKU '$SearchSku'.
A subscription may hold only one Free search service. Options:
  -SearchSku Basic     (also enables managed identity and semantic ranking)
  -SearchService <name of an existing service>
"@
}
$searchId = az search service show --name $SearchService --resource-group $ResourceGroup --query id -o tsv

# Data-plane role-based access is off by default. Turning it on is what lets the
# application query with a Microsoft Entra identity instead of an API key.
Write-Host "==> Enabling Microsoft Entra authentication on the search service..."
$patch = @{
    properties = @{
        authOptions = @{ aadOrApiKey = @{ aadAuthFailureMode = "http401WithBearerChallenge" } }
    }
}
$useManagedIdentity = $SearchSku -ne "Free"
if ($useManagedIdentity) { $patch["identity"] = @{ type = "SystemAssigned" } }

$patchFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($patchFile, ($patch | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))
az rest --method patch --uri "https://management.azure.com$($searchId)?api-version=2023-11-01" `
    --headers "Content-Type=application/json" --body "@$patchFile" --only-show-errors | Out-Null
$patchFailed = $LASTEXITCODE -ne 0
Remove-Item $patchFile -ErrorAction SilentlyContinue
if ($patchFailed) { throw "Could not enable Microsoft Entra authentication on $SearchService." }

Write-Host "==> Assigning search data-plane roles..."
Grant-Role $userId "User" "Search Service Contributor" $searchId
Grant-Role $userId "User" "Search Index Data Reader" $searchId

$rolesPath = Join-Path $root "roles.local.json"
if (Test-Path $rolesPath) {
    # Every persona may read the knowledge index. Who can change what the index
    # contains stays with App Configuration and with the content container.
    $roles = Get-Content $rolesPath -Raw | ConvertFrom-Json
    foreach ($personaName in $roles.personas.PSObject.Properties.Name) {
        $clientId = $roles.personas.$personaName.clientId
        $objectId = az ad sp list --filter "appId eq '$clientId'" --query "[0].id" -o tsv
        if ($objectId) { Grant-Role $objectId "ServicePrincipal" "Search Index Data Reader" $searchId }
    }
}

# --- Index, data source, indexer -------------------------------------------
Write-Host "==> Creating the index $IndexName..."
$index = [ordered]@{
    name   = $IndexName
    fields = @(
        [ordered]@{ name = "id"; type = "Edm.String"; key = $true; searchable = $false; filterable = $true; sortable = $false; facetable = $false }
        [ordered]@{ name = "title"; type = "Edm.String"; searchable = $true; filterable = $false; sortable = $true; facetable = $false }
        [ordered]@{ name = "content"; type = "Edm.String"; searchable = $true; filterable = $false; sortable = $false; facetable = $false }
        [ordered]@{ name = "url"; type = "Edm.String"; searchable = $false; filterable = $false; sortable = $false; facetable = $false }
        [ordered]@{ name = "industry"; type = "Edm.String"; searchable = $false; filterable = $true; sortable = $false; facetable = $true }
        [ordered]@{ name = "audience"; type = "Edm.String"; searchable = $false; filterable = $true; sortable = $false; facetable = $true }
        [ordered]@{ name = "status"; type = "Edm.String"; searchable = $false; filterable = $true; sortable = $false; facetable = $true }
        [ordered]@{ name = "effective_date"; type = "Edm.String"; searchable = $false; filterable = $true; sortable = $true; facetable = $false }
    )
}
if ($SearchSku -ne "Free") {
    $index["semantic"] = [ordered]@{
        configurations = @(
            [ordered]@{
                name              = "kb-semantic"
                prioritizedFields = [ordered]@{
                    titleField                = [ordered]@{ fieldName = "title" }
                    prioritizedContentFields  = @([ordered]@{ fieldName = "content" })
                    prioritizedKeywordsFields = @([ordered]@{ fieldName = "industry" })
                }
            }
        )
    }
}
# The first data-plane call is the one that waits for RBAC to propagate.
Invoke-SearchApi -Method PUT -Path "/indexes/$IndexName" -Body $index -RetrySeconds 300 | Out-Null

Write-Host "==> Creating the alias $AliasName -> $IndexName..."
Invoke-SearchApi -Method PUT -Path "/aliases/$AliasName" -Body ([ordered]@{ name = $AliasName; indexes = @($IndexName) }) | Out-Null

Write-Host "==> Creating the data source..."
if ($useManagedIdentity) {
    $searchPrincipalId = az search service show --name $SearchService --resource-group $ResourceGroup --query identity.principalId -o tsv
    if (-not $searchPrincipalId) { throw "The search service has no system-assigned identity." }
    Grant-Role $searchPrincipalId "ServicePrincipal" "Storage Blob Data Reader" $storageId
    $connectionString = "ResourceId=$storageId;"
}
else {
    Write-Warning "The Free tier does not support managed identity, so the indexer will use a storage account key. Use -SearchSku Basic for a keyless connection."
    $connectionString = az storage account show-connection-string --name $StorageAccount --resource-group $ResourceGroup --query connectionString -o tsv
}

$dataSource = [ordered]@{
    name        = "kb-blobs"
    type        = "azureblob"
    credentials = [ordered]@{ connectionString = $connectionString }
    container   = [ordered]@{ name = $Container }
    # Deletion detection is NOT automatic and is NOT retroactive. Configuring it
    # now, before the first run, is the whole point. A policy added later leaves
    # already-deleted documents in the index permanently.
    dataDeletionDetectionPolicy = [ordered]@{
        "@odata.type"          = "#Microsoft.Azure.Search.SoftDeleteColumnDeletionDetectionPolicy"
        softDeleteColumnName   = "IsDeleted"
        softDeleteMarkerValue  = "true"
    }
}
Invoke-SearchApi -Method PUT -Path "/datasources/kb-blobs" -Body $dataSource | Out-Null

Write-Host "==> Creating the indexer (hourly schedule)..."
$indexer = [ordered]@{
    name            = "kb-indexer"
    dataSourceName  = "kb-blobs"
    # An indexer cannot target an alias, so it writes to the concrete index.
    targetIndexName = $IndexName
    schedule        = [ordered]@{ interval = "PT1H" }
    parameters      = [ordered]@{
        batchSize     = 10
        configuration = [ordered]@{
            dataToExtract                = "contentAndMetadata"
            indexedFileNameExtensions    = ".md,.txt"
            failOnUnsupportedContentType = $false
        }
    }
    fieldMappings   = @(
        # Keys cannot contain the characters in a blob path, so it is encoded.
        [ordered]@{ sourceFieldName = "metadata_storage_path"; targetFieldName = "id"; mappingFunction = [ordered]@{ name = "base64Encode" } }
        [ordered]@{ sourceFieldName = "metadata_storage_path"; targetFieldName = "url" }
        [ordered]@{ sourceFieldName = "metadata_storage_name"; targetFieldName = "title" }
        # industry, audience, status and effective_date need no mapping: custom
        # blob metadata lands in index fields of the same name.
    )
}
Invoke-SearchApi -Method PUT -Path "/indexers/kb-indexer" -Body $indexer | Out-Null

Write-Host "==> Running the indexer..."
Invoke-SearchApi -Method POST -Path "/indexers/kb-indexer/run" | Out-Null
$indexed = $false
foreach ($attempt in 1..20) {
    Start-Sleep -Seconds 10
    $status = (Invoke-SearchApi -Method GET -Path "/indexers/kb-indexer/status") | ConvertFrom-Json
    $last = $status.lastResult
    if ($last -and $last.status -eq "success") {
        Write-Host "    Indexed $($last.itemsProcessed) documents, $($last.itemsFailed) failed."
        $indexed = $true
        break
    }
    if ($last -and $last.status -eq "transientFailure") { Write-Warning "    Transient failure: $($last.errorMessage)" }
    if ($last -and $last.status -eq "persistentFailure") { throw "Indexer failed: $($last.errorMessage)" }
}
if (-not $indexed) { Write-Warning "The indexer is still running. Check its status in the portal." }

# --- Update .env -----------------------------------------------------------
Write-Host "==> Updating .env..."
$searchEndpoint = "https://$SearchService.search.windows.net"
$envPath = Join-Path $root ".env"
$keep = @()
if (Test-Path $envPath) {
    $keep = Get-Content $envPath | Where-Object { $_ -notmatch '^AZURE_SEARCH_ENDPOINT=' -and $_.Trim() }
}
$envContent = (($keep + @("AZURE_SEARCH_ENDPOINT=$searchEndpoint")) -join "`n") + "`n"
[System.IO.File]::WriteAllText($envPath, $envContent, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "Knowledge layer ready."
Write-Host "  Storage account : $StorageAccount / $Container"
Write-Host "  Search service  : $SearchService ($SearchSku)"
Write-Host "  Index           : $IndexName, queried through the alias $AliasName"
Write-Host "  Deletion policy : soft delete on the IsDeleted blob metadata flag"
Write-Host ""
Write-Host "Next: pwsh scripts/seed-config.ps1 -AppConfigName $ProductionStore -DraftAppConfigName $baseName-draft-appcfg"
Write-Host "Then: streamlit run app.py    (open the Knowledge tab)"
