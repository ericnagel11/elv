# Support handoff: Azure AI Search HTTP 500

**Latest status (2026-09-15):** The customer supplied **HTTP 200** and
**SEARCH_QUERY_SUCCEEDED** for the authenticated zero-result query on
`medical-policies-vector`, API `2026-04-01`, following the successful OPTIONS 204.
The selected VM identity can now complete this query; the prior CMK error is no
longer blocking it. Exact customer-side repair actions have not been supplied.
Other indexes, document retrieval, schema compatibility and the browser CORS/POST
flow remain unverified. No more changes or repeated tests are needed for this
specific access check. This file is now a scoped recovery/incident record.

**Earlier diagnosis:** The replay exposed `UserAssignedIdentityNotDefined`, and
the customer confirmed the configured CMK identity was missing from Search's
User assigned Identity tab. The targeted repair instructions are retained as
history/reference. No Azure repair or support case has been performed by the
assistant. Share this resource/network metadata through approved internal/support
channels, not publicly.

**Suggested subject:** Azure AI Search CMK failure: UserAssignedIdentityNotDefined
prevents Key Vault wrap/unwrap and returns HTTP 500 during OPTIONS.

## Identified blocker and targeted repair

The customer ran the single unauthenticated OPTIONS replay and supplied
`HTTP=500 Remote=10.134.64.158` with an error body. The outer `error.code` is
empty; `error.message` reports that Search cannot use its Key Vault key to
wrap/unwrap the encryption key because of **UserAssignedIdentityNotDefined**:

> Could not get identity for service tenxeng-benefit-ai-search using user assigned
> managed identity .../userAssignedIdentities/apm1081142-gld-dtpqa-01-identity

Exact resource references from the response (identifiers, not secret key material):

- Configured CMK user-assigned identity resource ID:
  `/subscriptions/20659eb6-9c76-49ae-9f30-7c478bb5244d/resourcegroups/apm1081142-gld-dtpqa-01-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/apm1081142-gld-dtpqa-01-identity`.
- Vault: `https://apm1081142-dtpqa-01-kv.vault.azure.net`.
- Key name: `tenxeng-benefit-ai-certficate-6e0052ae035650ff1d2a3136ae00010052ae03`.
- Referenced version: `df09fb50135b420586737260c9d04c3d`.

Preserve the literal resource names. Despite the key name containing `certficate`,
the reference is a **/keys/** encryption-key endpoint, not a request for a
certificate or secret. Do not export private keys or retrieve secret values.

This establishes the server-reported CMK identity failure for the replayed
`medical-policies-vector` OPTIONS operation. It is a strong explanation to
investigate for the other indexes' 500s, but their CMK references and recovery
must still be verified. OPTIONS now returns 204 and the authenticated zero-result
query on `medical-policies-vector` returns 200; see validation below.

**Attachment check completed:** The customer answered **No, it is missing**
when asked to inspect the exact referenced identity under this Search service's
User assigned Identity tab. This is the concrete missing association matching
the error. Whether the UAMI resource itself still exists and its Key Vault grant
is sufficient remains to be checked before the approved restoration.

### Two distinct access relationships

| Connection | Identity/configuration | Required access |
| --- | --- | --- |
| VM application to Search | Selected VM-attached identity; customer confirmed query role | Search Index Data Reader, or existing Search Index Data Contributor |
| Search to Key Vault for CMK | Identity referenced by encryption configuration, attached to **Search itself** | Key Vault key metadata and wrap/unwrap permissions |

These identities may turn out to be the same underlying UAMI; that mapping has
not been established. Even if they are the same, attachment to the VM and Search
are separate. A query role in Search **Access control (IAM)** does not attach a
user-assigned identity to Search. Do not grant the VM runtime new Key Vault rights
or replace the query identity as a workaround.

### Owner action 1: verify and restore the intended Search identity association

The user-assigned attachment was confirmed absent before the latest 204 result.
The following is the repair guidance provided at that time; do not repeat changes
without inspecting current state. Exact actions taken have not been reported.

1. Open **tenxeng-benefit-ai-search > Settings > Identity > User assigned**.
   This is **Identity**, not Access control (IAM).
2. Verify that the exact referenced UAMI exists in the subscription/resource
   group listed above and is associated with this Search service.
3. If it exists but is absent from Search, have the authorized service owner use
   **Add** to associate that **existing approved identity** with Search. Keep all
   other user-assigned identities and any system-assigned identity intact.
   Attaching an identity lets Search use that identity's permissions; the owner
   must confirm this is the intended CMK configuration before making the change.
4. If the identity is missing/deleted, the reference is wrong, or it is already
   attached but still unavailable, do not create a same-name replacement or
   detach/recreate identities blindly. Have the owner review the configured
   CMK identity reference and recent Search/identity deployment changes, then
   involve Microsoft support if a valid association cannot be resolved. A
   recreated identity has a new principal ID and does not inherit the old grants.

### Owner action 2: verify key access for that identity

Only after the identity association is correct, verify the referenced identity's
access on **apm1081142-dtpqa-01-kv**:

- With Key Vault **Azure RBAC**, the purpose-built role is **Key Vault Crypto
  Service Encryption User**, ID `e147488a-f6f5-4113-8e2d-b22465e65bf6`. It permits
  reading key metadata and wrap/unwrap. Verify an existing sufficient assignment
  before adding one; use the approved key/vault scope, not subscription-wide access.
- With legacy **Vault access policy**, the corresponding key permissions are
  **Get**, **Wrap Key**, **Unwrap Key** for that identity. Do not switch the vault's
  permission model during repair; that can disrupt other applications.
- Use the UAMI's current **principal/object ID** for grants; it is different from
  its client ID and ARM resource ID. Secrets User, certificate roles and ordinary
  Key Vault Contributor are not substitutes for key wrap/unwrap permission.
- Have the key owner confirm that the exact referenced key version still exists,
  is enabled, is within its validity period and supports the required operations.
  Do not rotate, disable, delete, purge or replace it as a diagnostic experiment.
- Search must also reach Key Vault using the approved outbound CMK network path.
  VM-to-Search private connectivity does not validate Search-to-Key-Vault access.
  Investigate this if the subsequent error points to it; do not enable public
  access or alter firewall/trusted-service rules speculatively.

The captured error said Search **could not obtain the identity**, not that Key Vault
has returned a confirmed permissions denial. An extra role alone cannot repair
a missing identity association. Grant changes require the customer's authorized
RBAC/access-policy administrator; local Windows admin is not that authority.

### Validate after the approved repair

**Completed customer validation:**

| Field | Supplied result |
| --- | --- |
| Index | medical-policies-vector (target of the supplied invocation) |
| Operation / API | Query / 2026-04-01 |
| Request UTC | 2026-09-15T21:53:17.327Z |
| Client request ID | 0be81d8a-fe56-45e6-afe9-fd30bb65d5ec |
| Server request ID | 4f310f6f-e831-436a-80cf-adad9cf31015 |
| HTTP / content type | 200 / application/json |
| Probe result | SEARCH_QUERY_SUCCEEDED |

The selected managed identity completed the fixed `top=0` query, and the private
response check confirmed an empty document array. Empty results are intentional
and do not establish whether the index contains documents. No customer documents,
counts or tokens were displayed. This validates the minimal query path, not
full retrieval/decryption, vector/semantic search or document-level authorization.

The command below is the completed validation, retained for reference, **not a
request to repeat it**:

```powershell
& .\check-query.ps1 -Endpoint 'https://tenxeng-benefit-ai-search.search.windows.net' -IndexName 'medical-policies-vector' -ClientId 'c5224757-9cf0-4d8d-9ae3-e72ce1112447' -ApprovedAzureHost -Diagnostics -Operation Query -ApiVersion '2026-04-01'
```

Before using the other indexes, validate their read access and required schemas
separately; the original `medical-policies` and `vector-search-test` recovery has
not been reported. No further identity/CORS changes are indicated by this success.
For portal validation use the fixed zero-result JSON query, not a blank search
that would return documents. If the failure changes, investigate the new error
rather than repeatedly applying permissions or rerunning the full matrix.

Do not disable CMK, clear encryption configuration or recreate indexes. Restore
access to the existing key and preserve encrypted content. If the association
and key access are confirmed but Search still reports this error, submit this
handoff with the attachment evidence and request IDs to Microsoft support.

References: [Search CMK identity and permissions](https://learn.microsoft.com/en-us/azure/search/search-security-manage-encryption-keys),
[Attach a Search user-assigned identity](https://learn.microsoft.com/en-us/azure/search/search-how-to-managed-identities#create-a-user-assigned-managed-identity),
[Key Vault role definitions](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide#azure-built-in-roles-for-key-vault-data-plane-operations).

## Impact and target

- Minimal managed-identity query access is verified on `medical-policies-vector`.
  Full Windows PoC readiness and other-index recovery are pending; production
  impact is unknown.
- Service: `tenxeng-benefit-ai-search`.
- Endpoint: `https://tenxeng-benefit-ai-search.search.windows.net`.
- Execution host: customer Azure Windows Server VM, not the operator workstation.
- Selected VM-attached user-assigned managed identity client ID:
  `c5224757-9cf0-4d8d-9ae3-e72ce1112447` (not a secret or principal object ID).
- Azure CLI: `2.90.0`.
- Owner to attach the service ARM resource ID, subscription and region from the
  actual Azure resource when submitting; these have not been supplied here.

## Observed failures

All five requests below returned **HTTP 500**, response type **application/json**,
CLI exit **1**, and a server request UUID. The probe recognized no more specific
error category. Timestamps are recorded immediately before invoking the CLI, not
response-completion timestamps. UTC date for every row: **2026-09-15**.

| Index | Operation | API | UTC | Client request ID | Server request ID |
| --- | --- | --- | --- | --- | --- |
| medical-policies | Count | 2026-04-01 | 20:07:54.952Z | f9c9d1c1-888b-4650-b1e2-fb6b11a06a48 | 450119a0-c15b-4cc8-a3d8-cc52916d137f |
| medical-policies | Query | 2026-04-01 | 20:07:59.655Z | a80490b2-1b2d-4ce7-ac85-f8aa84f2d956 | 3e90e274-207c-4b6e-b97a-be1d8a9204e7 |
| vector-search-test | Count | 2026-04-01 | 20:08:04.179Z | 855aee3b-3c13-47a5-9041-b4617c886e6a | fed31fcb-56a9-4827-80de-f8b3e31e1823 |
| vector-search-test | Query | 2026-04-01 | 20:08:26.340Z | e326aeb6-a62e-4c2b-a32d-1b980a9401d6 | 0ab600d4-da36-43f8-845f-346a2b0f028d |
| medical-policies | Query | 2024-07-01 | 20:15:30.695Z | 6811c779-e016-4138-b51a-54d4d9629e92 | 431476e0-c239-4ccd-af37-d8caae7927d2 |

### Request shape (already executed, not a request to repeat)

- Explicit managed-identity sign-in through Azure CLI, using a private temporary
  credential cache; REST token audience `https://search.azure.com`.
- Count: GET `/indexes/{index}/docs/$count?api-version={version}`.
- Query: POST `/indexes/{index}/docs/search?api-version={version}` with
  `Content-Type: application/json` and the fixed body
  `{"search":"*","queryType":"simple","top":0,"count":false}`.
- Diagnostic requests send `x-ms-client-request-id` using the listed client UUID.
- Queries request zero documents. No vector/semantic/model operations, mutations
  or document-permission bypass headers are used. No document content or token
  is displayed. Private raw CLI logs and request/response files are cleaned up
  after each check, so they are not attached to this handoff.

### Separate portal observation: OPTIONS preflight returned 500

The customer is running Search Explorer in a browser **inside the customer VM**.
The latest Network-table screenshot establishes that the row with status 500 is
**OPTIONS**, type **preflight**, approximately 127 ms. The associated POST row
has no HTTP status and displays 0 B; this is not evidence of a portal POST 500.
The failed preflight prevents the actual query from being sent and explains the
portal's generic `TypeError: Failed to fetch` / `commonInvoke` wrapper.

The preceding URL screenshot identifies the portal target as
`/indexes/medical-policies-vector/docs/search?api-version=2026-05-01-preview` on
the same Search hostname. This is a different index/API combination from the
five managed-identity probes. No exact UTC, OPTIONS response body, remote address
or OPTIONS server request ID was available in that first capture. Do not reuse a
provisional POST client ID as an OPTIONS correlation ID.

**Subsequent OPTIONS Headers capture:**

- Remote Address: `10.134.64.158:443`, matching the VM's prior private DNS result.
- Response Date: `Tue, 15 Sep 2026 20:31:50 GMT` (server response time, not a CLI
  pre-request timestamp).
- Response Request-Id: `4d9e5e60-8f21-49e6-a6fc-135a582127b6`.
- Status: `500 Internal Server Error`; Content-Type:
  `application/json; charset=utf-8`; Content-Length: `786`; Elapsed-Time: `122`.
- Origin: `https://portal.azure.com`; Access-Control-Request-Method: `POST`.
- Access-Control-Request-Headers:
  `authorization,client-request-id,content-type,portal-controller,x-ms-client-request-id,x-ms-command-name,x-ms-operation-name`.
- No Access-Control-Request-Private-Network or Access-Control-Allow-* header is
  visible in the supplied capture.
- The customer initially reported no accessible Response body. A response did
  arrive and advertised a 786-byte JSON body; the later token-free replay exposed
  the CMK identity error documented above.
  This is not evidence that the server sent no response. The remote IP matches
  the expected private endpoint but does not independently establish the origin
  of the error or exclude a transparent intermediary.

Normal browser CORS preflight does not send the query's bearer token. Therefore
this is not evidence of the portal user's query-authorization result. The CLI
does not enforce browser CORS and its authenticated GET/POST requests also fail:
a browser-CORS-only explanation cannot account for all observations. The later
replay identifies a concrete CMK identity failure; whether it accounts for all
five earlier CLI failures must be established by recovery validation.

The [targeted preflight investigation](preflight-investigation.md) is retained as
the reproduction record. Its initial evidence-gathering goal is complete; follow
the targeted CMK repair above instead of further generic OPTIONS comparisons.

## Checks already completed or reported

- Customer confirms Search is RBAC-only; public network access is disabled.
- From the VM, the normal Search hostname resolves through the Private Link
  hostname to `10.134.64.158`; direct TCP 443 test succeeds to that address.
- `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` and `NO_PROXY` were reported unset
  before probing. This does not exclude system/transparent intermediaries.
- The selected VM identity signs in successfully. App Configuration read and
  synthetic OpenAI inference separately passed; they do not prove Search rights.
- An earlier IAM screenshot showed Search Index Data Contributor inherited from
  a resource group. The customer subsequently confirmed seeing the role for the
  selected VM identity in this Search resource's Check access view. The expected
  read-capable role assignment is present; no additional Reader role is needed.
  This is customer-confirmed assignment visibility, not proof that authorization
  completes successfully for the failed requests.
- Former Windows batch URL parsing and mismatched companion-script failures
  were fixed. Subsequent runs reach HTTP responses with correlation IDs.

## Requested investigation

1. **Search/identity owner:** verify the referenced identity exists and is attached
  to Search; review recent removals/replacements and the intended CMK reference.
2. **Key Vault owner:** verify that identity's current key-use permissions and
  availability of the exact key/version. Repair only missing approved access.
3. **Microsoft support, if needed:** correlate the known request IDs and CMK error
  if a valid identity association still cannot be resolved, or if another failure
  remains after repair. A generic healthy resource status does not clear this error.

No Log Analytics workspace is available. Built-in metrics do not require one;
query logs need a configured destination. Creating logging now cannot recover
earlier query logs, and a workspace is not required to open the support case.

Failures were not exclusive to one tested index, the count operation or API
`2026-04-01`; the specific error is now known for the OPTIONS replay. Recovery
is validated for the minimal query on `medical-policies-vector`, not the original
two indexes or full document retrieval. Do not repeat the successful check,
downgrade the apps, broaden query permissions, switch to API keys, recreate
indexes or enable public access as an unverified workaround.

Probe source and scope: [check-query.ps1](check-query.ps1),
[diagnose-access.ps1](diagnose-access.ps1), [README.md](README.md).