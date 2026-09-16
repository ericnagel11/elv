# Blob Storage: one-container read-access check

**Status (2026-09-15):** Customer supplied a storage account, an approved existing
container and the same VM-attached identity used for the successful App Configuration
and OpenAI probes. The customer ran this probe: MI login succeeded, then the
listing returned HTTP 403 with `AuthorizationPermissionMismatch`, CLI exit 1
and CLI version `2.90.0`. Prioritize effective data permissions, scope, conditions
and propagation for that identity; no missing role has yet been confirmed.
Successful listing and Private Link routing remain unverified. Search remains
paused and Log Analytics is deferred because the customer reports no workspace.

**Replacement target (2026-09-15):** The customer has since selected account
`tenxengbenefitaistandard` and reports the VM identity has access there. The
replacement container name and a successful probe result have not been supplied.
Do not continue role changes on the original account based on the historical
denial above. Reader versus Contributor depends on whether the identity will
only validate/read data or also upload onboarding content, as explained below.

## Onboarding permissions are different from the read probe

The **Reader** recommendation above is for verifying read access, not for seeding
documents. A container must exist for Blob-backed indexing, but it does not need
to be new. The customer's approved existing container can be reused if its content,
access policy and indexing scope fit the demo. No Blob permission grants access
to Search or App Configuration, and no Blob data role grants Azure RBAC assignment
rights or permission to create storage accounts.

| Work | Identity / operator | Intended Blob role and scope |
| --- | --- | --- |
| Run this listing probe | Approved VM identity | Storage Blob Data Reader on the selected container; an effective existing data Contributor/Owner also suffices |
| Upload/update demo files and their metadata | Approved setup operator or dedicated uploader identity | Storage Blob Data Contributor on only the PoC container(s) |
| Create new containers, if needed | Authorized provisioning operator | Container-create permission; Storage Blob Data Contributor at the account scope is a built-in option but grants access to all account containers/blobs. Prefer admin precreation, then container-scoped upload rights |
| Pull documents into Search indexes | Identity configured for the Search indexer/data source | Storage Blob Data Reader on the source PoC container(s), with a separate working Search-to-Blob network path |
| Answer questions in either current PoC | VM runtime/querying personas | No direct Blob permission required by the current application; they query Search and need Search Index Data Reader on their approved indexes |
| Administer POSIX ACLs on HNS storage | Designated storage administrator, only if required | Storage Blob Data Owner can provide these extra powers; neither the current seed uploads nor read-only indexers need it |

If the current VM identity is explicitly approved to upload the demo content,
container-scoped **Storage Blob Data Contributor** is appropriate for that work
and includes the probe's read permission. Do not assign Reader and Contributor
redundantly. Prefer a separate uploader/operator or remove its approved temporary
write grant after setup; a VM-wide managed identity is usable by other trusted
workloads/users on the VM, not just one PowerShell process. Routine model inference
does not require Blob writes. Avoid granting account-wide data access merely to
create two containers: an administrator can create them first. Role assignments,
account properties, private endpoints and DNS are separate administrator operations.

### Reuse safely for both PoCs

Recommended layout: reuse the storage **account** and use one PoC-only container
per PoC, either existing dedicated containers or newly approved ones. The existing
container can be assigned to one PoC if suitable. Separate containers provide
clearer permission scopes and avoid mixing unrelated indexed content.

- [PoC001's setup](../../pocs/001-config-driven-responses/scripts/setup-knowledge.ps1)
  uploads manifest files at container root; its default Search data source scans
  the container without a folder restriction.
- [PoC002's setup](../../pocs/002-regional-multilingual-experience/scripts/setup-knowledge.ps1)
  uploads under `en/`, `de/` and `es/`, with a data source per language folder.
- Reusing one mixed container for both is possible only after agreeing isolated
  prefixes and updating both upload paths and data-source folder scopes. Otherwise
  PoC001 can index PoC002/unrelated content even when blob names do not collide.
  A virtual folder/prefix is an indexing filter, not an RBAC boundary by itself.
- Review approved documents and required metadata before ingestion, including
  PoC002 translation-status fields. Agree deletion detection before the first
  indexer run; the current scripts use an `IsDeleted` metadata marker, not storage
  account soft-delete/versioning configuration.

**Do not run the legacy setup scripts unchanged against shared services.** Their
`StorageAccount`, `Container` and `SearchService` parameters choose names, not a
reuse-only mode. Both still call storage-account/container/Search-service creation,
assign roles, patch Search authentication/identity, upload matching blob names with
`--overwrite`, and PUT Search definitions. They also assume a signed-in human user
when obtaining the setup principal. Blob Data Contributor alone does not authorize
all those operations or make the scripts managed-identity-safe. Customer onboarding
must skip provisioning of reused resources, preserve existing content/settings and
separate approved seeding from administrator role/network changes.

## Endpoint choice matters

The supplied `-microsoftrouting.blob.core.windows.net` URL is a **route-specific
public endpoint**, not evidence of a private endpoint. Microsoft's
[routing preference guidance](https://learn.microsoft.com/azure/storage/common/network-routing-preference#regional-availability)
lists a known HTTP 404 issue for Microsoft-global-network route-specific endpoints.

For this probe, the standard endpoint is explicitly derived from the supplied
account: `https://ACCOUNT.blob.core.windows.net/`. This is the same account, not
a new resource or a change to its routing policy. The customer's private DNS can
resolve that hostname to a Blob private endpoint where configured. Do not use a
`privatelink` hostname or IP address as the application endpoint. Account-specific
DNS/network access still requires VM validation; success on another Azure service
does not establish this route. Sovereign clouds, custom domains and Azure DNS-zone
storage endpoint variants are outside this narrow probe's scope.

## What the probe does

[check-access.ps1](check-access.ps1) uses Windows PowerShell 5.1/7 and installed Azure
CLI. No Python, PoC packages, API keys, SAS or connection strings are needed.

1. Checks host acknowledgement, account/container syntax and the explicit UAMI client ID.
2. Secures a fresh temporary CLI cache parent to the current Windows identity and SYSTEM.
3. Signs in as that attached user-assigned identity, not an operator's cached login.
4. Runs `az storage blob list` for **one named container**, `--auth-mode login`,
   `--num-results 1`, the explicit standard Blob endpoint and `--output none`.
5. Restores the caller environment and removes private cache/diagnostic files.

The limited list may retrieve a blob name and standard properties to the CLI,
but neither those fields nor continuation markers are displayed. No optional
metadata, tags, deleted blobs, snapshots or versions are requested, and **no file
contents are downloaded**. `--show-next-marker` puts any continuation marker in
the suppressed result instead of a warning; the script never follows it.
An empty container is a successful result, not an error.

The script never lists containers/accounts, reads storage keys, generates SAS,
uploads/deletes files, creates containers, edits access policies or changes Azure
RBAC/networking. Inherited storage credentials, account/endpoint/auth-mode overrides
and service-principal credentials are cleared for the probe and restored afterward.
Explicit `--auth-mode login` avoids the CLI's legacy account-key lookup path.
Extension auto-installation is disabled for the probe. No automatic endpoint or
credential fallback is implemented.

There is one list **command**, no script retry loop or bulk inventory. Azure CLI/SDK
may internally retry transient failures; `--timeout 30` applies to each service
request, not a hard 30-second process deadline. Normal Storage transactions and
service logs may apply. Nothing is sent to a model.

## Run on the customer VM

The VM must be approved for this identity/account/container. A usual minimum
role is **Storage Blob Data Reader**, scoped to the approved container where
appropriate. Existing stronger data roles may suffice; don't add redundant roles.
Control-plane Reader/Contributor or OpenAI/App Configuration roles alone do not
provide Blob content access. On hierarchical-namespace accounts, applicable ACLs
and ABAC conditions also need review. Do not change them automatically on failure.

Keep the customer's firewall, public-access, private-DNS and TLS/CA policies intact.
Existing proxy settings are preserved, with IMDS/loopback appended to proxy bypasses.
No new public access or system-wide proxy bypass is enabled.

Copy the standalone script to the VM via the approved source-transfer route.
Use a separate folder from the App Configuration probe, which has the same
filename; do not overwrite that previously validated script.
From an already-open PowerShell window in its folder, substitute the nonsecret values:

```powershell
& .\check-access.ps1 -AccountName 'YOURACCOUNT' -ContainerName 'YOUR-CONTAINER' -ClientId 'YOUR-UAMI-CLIENT-UUID' -ApprovedAzureHost -Diagnostics
```

Do not dot-source the script or bypass execution/signing policy. The acknowledgement
is not proof of host identity or an access grant. No administrator elevation is
needed for the test itself. All VM administrators still control the cache and
attached identities; separate Windows users are not managed-identity isolation.

## Results and safe diagnostics

| Exit | Meaning |
| --- | --- |
| 0 | `BLOB_READ_SUCCEEDED`: the selected identity completed a limited container listing. |
| 2 | Invalid input, unapproved host, missing CLI or private-cache/probe failure. |
| 3 | Explicit MI login failed; no listing attempted. |
| 4 | Listing failed; inspect the fixed category and optional diagnostics. |
| 5 | Temporary-cache cleanup failed; arrange secure local cleanup. |

`-Diagnostics` captures verbose list logs **privately**, not on the console. On
failure it also reads the CLI version locally, then prints only a fixed stage,
numeric exit code, numeric HTTP status if available, an allowlisted Storage error
code/category and a validated CLI version. Unknown values stay `UNKNOWN` rather
than exposing raw messages. No `--debug`, request headers, tokens, SAS, arbitrary
error text or blob properties are printed. Share only the fixed summaries.

- **403 / AuthorizationPermissionMismatch:** the requested operation was not
  authorized with the supplied permissions. With this probe's explicit Entra
  login, check the VM identity's effective Blob data role, scope, conditions and
  propagation first. This is not a SAS-permission test.
- **403 / AuthorizationFailure:** account/network restrictions are also common
  causes; do not assume that another role will fix the failure.
- **401 / AuthenticationFailed:** check identity, tenant and Storage token handling.
- **404 / ContainerNotFound:** check the account/container and standard endpoint;
  don't create or rename resources to suppress an error.
- **DNS/TLS/timeout:** inspect DNS, approved private endpoint path, firewall, proxy
  and certificate trust on the VM. A TCP check alone doesn't verify RBAC or TLS.
- **5xx / ServerBusy:** investigate service health with the owner, not broader roles.

For the reported permission mismatch, inspect **Access control (IAM)** at the
approved container and its inherited scopes. Select the managed identity attached
to the VM, not the operator's Windows/portal account and not the storage account's
outbound identity. `List Blobs` requires
`Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read`; the least
privileged built-in role is **Storage Blob Data Reader**. Existing **Storage Blob
Data Contributor** or **Storage Blob Data Owner** already include this permission
subject to scope/conditions, so no redundant Reader assignment is needed.

If no appropriate grant exists, request an authorized Azure administrator to
assign the approved read role at the **container scope**, not subscription scope.
If a grant exists, verify the principal/object ID matches the selected UAMI,
applicable conditions/deny assignments and, for HNS ACL-based access, directory
permissions. Do not remove intentional restrictions; a prefix-scoped permission
may require a separately agreed scoped test rather than a container-wide grant.
Allow propagation after an approved change before rerunning the unchanged probe;
Microsoft documents up to 10 minutes for role changes, with some identity/cache
scenarios taking longer. No key fallback or public-access change is needed for
this permission investigation.

There is no permanent diagnostic export. Private temporary files are removed in
`finally`; a host crash or uncatchable termination can prevent cleanup. Handle any
reported leftovers according to the customer's credential-cache policy.

## What success does not establish

- Permission to download every individual blob or upload/delete/seed content.
- That the connection used Private Link rather than an allowed public route.
- **Search indexer → Blob Storage** connectivity or identity permissions. The
  indexer runs in Search, not on the VM, and needs its own approved access path.
- Content suitability, container layout, full PoC functionality or audit ingestion.

## Offline tests

These invoke only local launcher-shaped batch fixtures, never real Azure CLI,
IMDS, Storage or Search. Run from the repository root on Windows:

```powershell
& .\deployment\appconfig\tests\test-check-access.ps1 -ProbePath (Join-Path $PWD 'deployment\storage\check-access.ps1')
& .\deployment\storage\tests\test-check-access.ps1
```

They cover native exit codes, launcher parsing, target validation, explicit
endpoint/authentication, one-result scope, inherited credential/endpoint removal,
private ACLs, redaction, empty-container success, failure categories, safe
diagnostics and environment restoration/cleanup. Real VM execution and CLI/SDK
integration still require the customer-run probe.

On 2026-09-15 the native-wrapper and mocked Blob suites passed in local Windows
PowerShell 5.1, including the launcher-level and inherited-credential tests.
Editor diagnostics reported no errors. No real Azure CLI, IMDS or Storage calls
were made by the tests or the assistant. Separately, the customer-run probe
produced the permission denial recorded above; successful Blob listing and
PowerShell 7 execution remain unverified.

References: [Blob list CLI](https://learn.microsoft.com/cli/azure/storage/blob#az-storage-blob-list),
[Storage Private Link](https://learn.microsoft.com/azure/storage/common/storage-private-endpoints),
[List Blobs permissions](https://learn.microsoft.com/rest/api/storageservices/list-blobs#authorization),
[Blob role assignments](https://learn.microsoft.com/azure/storage/blobs/assign-azure-role-data-access),
[Authorize Blob operations with CLI](https://learn.microsoft.com/azure/storage/blobs/authorize-data-operations-cli).