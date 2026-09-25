# Blob Storage: one-container read-access check

**Status (2026-09-15):** Customer supplied a storage account, an approved existing
container and the same VM-attached identity used for the successful App Configuration
and OpenAI probes. The customer ran this probe: MI login succeeded, then the
listing returned HTTP 403 with `AuthorizationPermissionMismatch`, CLI exit 1
and CLI version `2.90.0`. Prioritize effective data permissions, scope, conditions
and propagation for that identity; no missing role has yet been confirmed.
Successful listing and Private Link routing remain unverified. That investigation
paused Search and deferred Log Analytics because the customer reported no workspace.
PoC001's new default Blob application-history path does not require one; PoC002's
legacy Log Analytics requirement is unchanged.

**Replacement target (2026-09-15):** The customer has since selected account
`tenxengbenefitaistandard` and reports the VM identity has access there. The
replacement knowledge-container name and a successful probe result have not been supplied.
Do not continue role changes on the original account based on the historical
denial above. Reader versus Contributor depends on whether the identity will
only validate/read data or also upload onboarding content, as explained below.

## PoC001 application change history

### Windows single-identity comparison option (2026-09-23)

The user approved reusing the existing VM runtime identity for configuration
history in the limited comparison workflow. On 2026-09-22, a separately authorized
setup created **poc001-config-history** privately in **tenxengbenefitaistandard**,
enabled the local flag and was followed by a UI restart. On 2026-09-23 the user
confirmed live configuration save/readback. This supersedes the initial
implementation-only restriction for that setup and test; it does not verify
access to the separate knowledge container discussed above. Follow the
[Windows activation steps](../windows/README.md#configuration-change-history-in-blob-storage).

An optional, separate [Windows setup script](../windows/prepare_history.py) now
previews the configured target locally and, only with `--apply --approved-azure-host`,
creates the missing private container and enables the local history flag after
verification. It reuses an existing private container, refuses an existing public
one without changing its policy, and makes no role/account/network changes or
test uploads. Existing permission to create the container is required; a 403 is
not permission to grant account-wide access. The successful apply and subsequent
user-confirmed test are recorded in the
[validation record](../../specs/003-redhat-vm-hosting/validation.md#history-activation-and-user-acceptance-2026-09-23).
See [scripted setup](../windows/README.md#scripted-container-setup-and-local-activation).

Set `ELV_ENABLE_CONFIG_HISTORY=true` only after the authorized storage owner
creates/confirms the dedicated private container and the selected VM identity's
effective read/create permission (normally container-scoped Storage Blob Data
Contributor). This mode explicitly uses `ELV_MI_APP_CLIENT_ID` for both writing
and reading; it does not silently borrow another credential. No separate audit
identity, Log Analytics workspace, key or SAS is needed for this approved mode.

Individual and grouped live configuration edits use version checks, preserve
known before/after values and display logging warnings separately. No-op changes
do not create events; no questions, generated answers, retrieved documents or
raw errors are stored. A Change history tab reads only after explicit Refresh.
This is **not independent or immutable auditing**: the shared identity can read
and change history, and all local VM users/code share its trust boundary.
Successful save/readback establishes that path, not the exact role scope,
retention/lifecycle configuration, Private Link routing or live failure behavior.
Those require separate owner evidence; no broader permission is implied.

### Full-governance identity policy (unchanged)

This is **separate from knowledge onboarding and Search indexing**. Use the
existing account endpoint `https://tenxengbenefitaistandard.blob.core.windows.net`
and a dedicated **private, owner-precreated** container, `poc001-config-history`.
The configured name does not prove container existence, approval, access or
Private Link routing. Keep customer documents and indexer data sources out of
this container. Do not reuse the previously probed identity implicitly.

| Setting / identity | Deployment input / minimum intended grant |
| --- | --- |
| `ELV_AUDIT_BACKEND` | `blob` (PoC001 default); no Log Analytics workspace required |
| `ELV_AUDIT_BLOB_ACCOUNT_URL` | `https://tenxengbenefitaistandard.blob.core.windows.net`, no SAS, credentials, query or container path |
| `ELV_AUDIT_BLOB_CONTAINER` | `poc001-config-history`, dedicated and private |
| `ELV_AUDIT_BLOB_WRITER_CLIENT_ID` | Separate VM-attached UAMI client UUID, distinct from all persona UUIDs and the reader; **Storage Blob Data Contributor on this container only** |
| `ELV_MI_AUDIT_CLIENT_ID` | Existing dedicated audit reader selector; **Storage Blob Data Reader on this container only** |

These are administrator prerequisites, not app provisioning instructions. Do not
grant account-, subscription- or root-wide data access. A prefix is not an RBAC
boundary. The application never creates/overwrites the container, changes roles,
access policies, public access, network rules or retention, and never obtains
account keys or SAS. Retention/lifecycle decisions remain with the resource owner.
Windows administrator elevation is not Azure role-assignment authorization.
Development mode uses the developer credential instead of these VM selectors;
it does not demonstrate VM writer/reader separation.

The writer attempts one uniquely named JSON block blob with `overwrite=False`
per application configuration event; there is no shared CSV append. It records
allowlisted experience/knowledge before/after values, outcome, operation group
and configured service-persona attribution. It does **not** record direct
Portal/CLI/seed/provisioning edits or backfill old changes, and it does not prove
human identity. Do not enter PHI, tokens, secrets or personal data into the
configuration being recorded. Questions, retrieved documents and model prompts
are not history payloads.

Missing/invalid Blob settings or writer UUID, storage denial and upload failures
produce best-effort warnings without changing the configuration write's outcome
or blocking response generation. Startup deliberately does not validate Blob
URL/container/writer; normal persona and audit-reader validation is retained.
Reader failures mean **history unavailable**, not an empty successful result.
Reads are bounded to at most 30 days and 500 returned events with additional
listing/download budgets and explicit partial warnings. CSV exports only the
selected visible rows, quotes fields and neutralizes spreadsheet formulas.

Create-only application writes are **not immutable/WORM storage**: the writer's
Contributor role permits overwrite/delete, and crashes or storage outages can
leave gaps. There is no atomic App Configuration/Blob transaction, local outbox
or automatic Log Analytics fallback. Explicit `ELV_AUDIT_BACKEND=loganalytics`
is the optional legacy PoC001 path; PoC002 remains LA-required regardless of this
environment value.

Deploy the matching application integration, dependencies and environment
settings before accepting UI history/warnings/CSV. Nothing here automatically
creates resources or grants roles. See the
[PoC001 runbook](../../pocs/001-config-driven-responses/README.md) and
[Linux deployment example](../redhat/poc001.env.example). A successful listing
probe alone does not verify event uploads, downloads or application integration.

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
| Answer questions in either current PoC | VM runtime/querying personas | No direct Blob permission required for inference/retrieval; they query Search and need Search Index Data Reader on approved indexes. PoC001 history uses separate writer/reader identities above |
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

Recommended knowledge layout: reuse the storage **account** and use one PoC-only
source container per PoC, plus PoC001's separate history container above. Use
existing dedicated containers or newly approved ones. The existing
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