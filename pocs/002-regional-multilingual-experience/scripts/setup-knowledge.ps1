#Requires -Version 5.1
<#
.SYNOPSIS
    Adds the multilingual knowledge layer: a storage account holding governed
    content in per-language folders, one Azure AI Search index per language with
    that language's analyzer, and one indexer per language.

.DESCRIPTION
    Run this AFTER scripts/setup.ps1 (and ideally after setup-governance.ps1, so
    the persona service principals exist and can be granted query access).

    What it creates, for each of en, de and es:

      kb-<lang>-v1        the search index, with that language's analyzer
      kb-<lang>-current   an index alias, which is what the app queries
      kb-<lang>-blobs     the data source, scoped to the language's folder
      kb-<lang>-indexer   the indexer, on an hourly schedule

    Why one index per language rather than one index with a language filter:
    the Azure AI Search 'analyzer' property is set on a FIELD and is fixed when
    the index is created. There is no per-document analyzer. Getting German
    decompounding and Spanish lemmatization therefore requires either a field
    per language or an index per language. Market documents here are independent
    rather than parallel translations (the German withdrawal policy is a
    different policy, not a translation of the American returns policy), so an
    index per language is the better fit and a rebuild of one market leaves the
    others untouched.

    Three languages is also exactly the Free tier's limit of three indexes,
    three indexers and three data sources, which keeps this demonstration free.

    Two carry-overs from proof of concept 001 that still matter:

    1. The deletion detection policy is configured on the FIRST indexer run.
       A policy added later will not retroactively remove documents deleted
       before it existed, and the only remedy then is a new index.

    2. Queries go to the alias, never to the concrete index. An indexer cannot
       target an alias, so the indexer writes to kb-<lang>-v1 and the alias is
       repointed to publish or roll back a whole language's knowledge set.

.NOTES
    Managed identity requires the Basic tier or higher. On the Free tier the
    indexer authenticates to storage with an account key, which the script will
    do while warning about it. Semantic ranking also requires Basic or higher;
    the app falls back to keyword ranking and says so.

.EXAMPLE
    pwsh scripts/setup-knowledge.ps1 -ProductionStore regml4751-appcfg
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-poc-regional-multilingual",
    [Parameter(Mandatory = $true)][string]$ProductionStore,
    [string]$Location = "eastus",
    [ValidateSet("Free", "Basic", "Standard")][string]$SearchSku = "Free",
    [string]$StorageAccount,
    [string]$SearchService,
    [string]$Container = "knowledge",
    # Must be a version that exposes /aliases. 2024-07-01 does not.
    [string]$SearchApiVersion = "2026-04-01"
)

$ErrorActionPreference = "Stop"

# Language code to Microsoft analyzer. The Microsoft analyzers are used rather
# than the Lucene ones because they perform lemmatization and, for German,
# decompounding, which is exactly where a language-agnostic tokenizer fails.
$Analyzers = [ordered]@{
    en = "en.microsoft"
    de = "de.microsoft"
    es = "es.microsoft"
}

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
# Metadata travels with the content, not with the code. Raising a document from
# 'reviewed' to 'certified' is a metadata change made by a content steward, and
# it is what the certification gate selects on.
Write-Host "==> Uploading governed content with metadata..."
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$languages = @()
foreach ($document in $manifest.documents) {
    $folder = $document.folder
    if (-not $folder) { throw "Manifest entry $($document.file) has no 'folder'." }
    if ($languages -notcontains $folder) { $languages += $folder }

    $path = Join-Path (Join-Path $knowledgeDir $folder) $document.file
    if (-not (Test-Path $path)) { throw "Manifest references a missing file: $folder/$($document.file)" }

    # 'file' and 'folder' are instructions to this script, not content metadata.
    $metadata = @()
    foreach ($property in $document.PSObject.Properties) {
        if ($property.Name -in @("file", "folder")) { continue }
        if ($null -eq $property.Value -or "$($property.Value)" -eq "") { continue }
        $metadata += "$($property.Name)=$($property.Value)"
    }

    az storage blob upload --account-name $StorageAccount --container-name $Container `
        --name "$folder/$($document.file)" --file $path --content-type "text/plain" `
        --metadata @metadata --overwrite --auth-mode login --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not upload $folder/$($document.file)." }
    Write-Host "    $folder/$($document.file)  [review=$($document.translation_status), jurisdiction=$($document.jurisdiction)]"
}

foreach ($lang in $languages) {
    if (-not $Analyzers.Contains($lang)) {
        throw "The manifest uses folder '$lang' but no analyzer is mapped for it. Add one to `$Analyzers."
    }
}
Write-Host "==> Languages found in the manifest: $($languages -join ', ')"

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
    # Every persona may read every language index. Which of that content may
    # answer in which market stays with App Configuration, not with RBAC.
    $roles = Get-Content $rolesPath -Raw | ConvertFrom-Json
    foreach ($personaName in $roles.personas.PSObject.Properties.Name) {
        $clientId = $roles.personas.$personaName.clientId
        $objectId = az ad sp list --filter "appId eq '$clientId'" --query "[0].id" -o tsv
        if ($objectId) { Grant-Role $objectId "ServicePrincipal" "Search Index Data Reader" $searchId }
    }
}

# --- Connection used by every indexer ---------------------------------------
if ($useManagedIdentity) {
    $searchPrincipalId = az search service show --name $SearchService --resource-group $ResourceGroup --query identity.principalId -o tsv
    if (-not $searchPrincipalId) { throw "The search service has no system-assigned identity." }
    Grant-Role $searchPrincipalId "ServicePrincipal" "Storage Blob Data Reader" $storageId
    $connectionString = "ResourceId=$storageId;"
}
else {
    Write-Warning "The Free tier does not support managed identity, so the indexers will use a storage account key. Use -SearchSku Basic for a keyless connection."
    $connectionString = az storage account show-connection-string --name $StorageAccount --resource-group $ResourceGroup --query connectionString -o tsv
}

# --- One index, alias, data source and indexer per language ------------------
$first = $true
foreach ($lang in $languages) {
    $indexName = "kb-$lang-v1"
    $aliasName = "kb-$lang-current"
    $dataSourceName = "kb-$lang-blobs"
    $indexerName = "kb-$lang-indexer"
    $analyzer = $Analyzers[$lang]

    Write-Host "==> [$lang] Creating the index $indexName (analyzer $analyzer)..."
    $index = [ordered]@{
        name   = $indexName
        fields = @(
            [ordered]@{ name = "id"; type = "Edm.String"; key = $true; searchable = $false; filterable = $true; sortable = $false; facetable = $false }
            [ordered]@{ name = "title"; type = "Edm.String"; searchable = $true; filterable = $false; sortable = $true; facetable = $false; analyzer = $analyzer }
            [ordered]@{ name = "content"; type = "Edm.String"; searchable = $true; filterable = $false; sortable = $false; facetable = $false; analyzer = $analyzer }
            [ordered]@{ name = "url"; type = "Edm.String"; searchable = $false; filterable = $false; sortable = $false; facetable = $false }
            [ordered]@{ name = "status"; type = "Edm.String"; searchable = $false; filterable = $true; sortable = $false; facetable = $true }
            [ordered]@{ name = "effective_date"; type = "Edm.String"; searchable = $false; filterable = $true; sortable = $true; facetable = $false }
            [ordered]@{ name = "language"; type = "Edm.String"; searchable = $false; filterable = $true; sortable = $false; facetable = $true }
            [ordered]@{ name = "jurisdiction"; type = "Edm.String"; searchable = $false; filterable = $true; sortable = $false; facetable = $true }
            [ordered]@{ name = "translation_status"; type = "Edm.String"; searchable = $false; filterable = $true; sortable = $false; facetable = $true }
            [ordered]@{ name = "version"; type = "Edm.String"; searchable = $false; filterable = $true; sortable = $false; facetable = $false }
            [ordered]@{ name = "source_document"; type = "Edm.String"; searchable = $false; filterable = $true; sortable = $false; facetable = $true }
            [ordered]@{ name = "source_version"; type = "Edm.String"; searchable = $false; filterable = $true; sortable = $false; facetable = $false }
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
                        prioritizedKeywordsFields = @([ordered]@{ fieldName = "jurisdiction" })
                    }
                }
            )
        }
    }
    # The first data-plane call is the one that waits for RBAC to propagate.
    $retry = if ($first) { 300 } else { 0 }
    Invoke-SearchApi -Method PUT -Path "/indexes/$indexName" -Body $index -RetrySeconds $retry | Out-Null
    $first = $false

    Write-Host "==> [$lang] Creating the alias $aliasName -> $indexName..."
    Invoke-SearchApi -Method PUT -Path "/aliases/$aliasName" `
        -Body ([ordered]@{ name = $aliasName; indexes = @($indexName) }) | Out-Null

    Write-Host "==> [$lang] Creating the data source $dataSourceName (folder '$lang')..."
    $dataSource = [ordered]@{
        name                        = $dataSourceName
        type                        = "azureblob"
        credentials                 = [ordered]@{ connectionString = $connectionString }
        # 'query' scopes the data source to one virtual folder, which is how a
        # single container feeds several language indexes.
        container                   = [ordered]@{ name = $Container; query = $lang }
        dataDeletionDetectionPolicy = [ordered]@{
            "@odata.type"         = "#Microsoft.Azure.Search.SoftDeleteColumnDeletionDetectionPolicy"
            softDeleteColumnName  = "IsDeleted"
            softDeleteMarkerValue = "true"
        }
    }
    Invoke-SearchApi -Method PUT -Path "/datasources/$dataSourceName" -Body $dataSource | Out-Null

    Write-Host "==> [$lang] Creating the indexer $indexerName..."
    $indexer = [ordered]@{
        name            = $indexerName
        dataSourceName  = $dataSourceName
        # An indexer cannot target an alias, so it names the concrete index.
        targetIndexName = $indexName
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
            [ordered]@{ sourceFieldName = "metadata_storage_path"; targetFieldName = "id"; mappingFunction = [ordered]@{ name = "base64Encode" } }
            [ordered]@{ sourceFieldName = "metadata_storage_path"; targetFieldName = "url" }
            [ordered]@{ sourceFieldName = "metadata_storage_name"; targetFieldName = "title" }
        )
    }
    Invoke-SearchApi -Method PUT -Path "/indexers/$indexerName" -Body $indexer | Out-Null

    Write-Host "==> [$lang] Running the indexer..."
    Invoke-SearchApi -Method POST -Path "/indexers/$indexerName/run" | Out-Null
    $indexed = $false
    foreach ($attempt in 1..20) {
        Start-Sleep -Seconds 10
        $status = (Invoke-SearchApi -Method GET -Path "/indexers/$indexerName/status") | ConvertFrom-Json
        $last = $status.lastResult
        if ($last -and $last.status -eq "success") {
            Write-Host "    Indexed $($last.itemsProcessed) documents, $($last.itemsFailed) failed."
            $indexed = $true
            break
        }
        if ($last -and $last.status -eq "persistentFailure") { throw "Indexer $indexerName failed: $($last.errorMessage)" }
    }
    if (-not $indexed) { Write-Warning "Indexer $indexerName has not reported success yet. It runs hourly and will catch up." }
}

# --- .env ------------------------------------------------------------------
Write-Host "==> Updating .env..."
$envPath = Join-Path $root ".env"
$keep = @()
if (Test-Path $envPath) {
    $keep = Get-Content $envPath | Where-Object { $_ -notmatch '^AZURE_SEARCH_ENDPOINT=' -and $_.Trim() }
}
$envContent = (($keep + @("AZURE_SEARCH_ENDPOINT=https://$SearchService.search.windows.net")) -join "`n") + "`n"
[System.IO.File]::WriteAllText($envPath, $envContent, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "Done."
Write-Host "Aliases created: $(($languages | ForEach-Object { "kb-$_-current" }) -join ', ')"
Write-Host "Each market's knowledge:index key already points at its alias."
Write-Host "Restart the app to pick up AZURE_SEARCH_ENDPOINT."
