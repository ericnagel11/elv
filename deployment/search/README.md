# Azure AI Search: read-access checks and bounded diagnostics

**Latest result (2026-09-15 21:53:17.327Z):** The customer supplied **HTTP 200** and
**SEARCH_QUERY_SUCCEEDED** for the fixed `top=0` query on `medical-policies-vector`
using the selected VM managed identity and API `2026-04-01`, after OPTIONS returned
204. Minimal VM-to-Search query access is verified for this index. The empty array
is intentional, not evidence that the index contains no documents. See the
[successful validation record](support-handoff.md#validate-after-the-approved-repair).
Other-index recovery, schemas, document retrieval, vector/semantic operations,
document-level permissions and browser CORS/POST remain unverified. No further
script replacement or speculative identity/CORS change is indicated.

The prior replay exposed **UserAssignedIdentityNotDefined** for Search's
customer-managed encryption key, and the customer confirmed the referenced UAMI
was missing from **Search > Settings > Identity > User assigned**. The
[targeted repair](support-handoff.md#identified-blocker-and-targeted-repair) and
[reproduction record](preflight-investigation.md) are retained. Exact customer-side
changes have not been supplied; no Azure changes were performed by the assistant.

**Status (2026-09-14):** The customer ran the probe and reported
`SEARCH_READ_FAILED` after managed-identity sign-in succeeded. The diagnostic
rerun identified `cli_exit=255`, `http_status=UNKNOWN`, `error_kind=SHELL_SYNTAX`
and Azure CLI `2.90.0`. The original `indexes('name')` URL reproduces exit 255
in a local CLI-shaped batch launcher before its command handler runs. The probe
now uses the equivalent `/indexes/name/docs/$count` route without parentheses.
The customer reran the corrected script and supplied `cli_exit=1`,
`http_status=500`, `error_kind=NONE_RECOGNIZED`, CLI `2.90.0`. The shell failure
is no longer reported; an HTTP server error was observed. The summary alone
does not establish the error's origin (Search or an intermediary), a missing
role, or an index/API compatibility issue. Successful Search access was then
unverified; the later scoped success is recorded above. No Azure configuration
changes have been made by this probe.
The customer has supplied an existing Search service, approved indexes and the
same VM-attached user-assigned identity used in the successful App Configuration
read and OpenAI inference checks. Those successes do not grant or prove Search
permissions. The existing indexes have not been validated for PoC compatibility.

**Update (2026-09-15):** Customer confirmed RBAC-only authentication, private DNS
resolution to `10.134.64.158` and successful direct TCP 443 connectivity. No
HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY environment variables were configured.
These facts do not establish CLI routing/TLS end to end or explain the 500.
The earlier IAM screenshot included Search Index Data Contributor inherited from
a resource group. The customer subsequently confirmed seeing that role for the
selected identity in the Search resource's Check access view. The expected query
role assignment is present; do not add a redundant Reader or broader role. This
confirms the visible assignment, not a successful authorization/query result.
The customer has requested renewed Search investigation using other diagnostics.

### Customer-VM results: HTTP 500 across operations, indexes and API versions

On **2026-09-15 at 20:07-20:08 UTC**, the customer completed the Count/Query
comparison on `medical-policies` and `vector-search-test` using API `2026-04-01`,
Azure CLI `2.90.0` and the selected VM identity. Every case returned HTTP 500,
`application/json`, a server request UUID, CLI exit 1 and probe exit 4. The
comparison completed; the earlier companion-parameter mismatch is no longer
blocking that run. No successful Search read had been established at that point.

Support correlation evidence supplied by the customer (timestamps are recorded
immediately before each CLI request, not response-completion times):

| Index / operation | Request UTC, 2026-09-15 | Client request ID | Server request ID |
| --- | --- | --- | --- |
| medical-policies / Count | 20:07:54.952Z | f9c9d1c1-888b-4650-b1e2-fb6b11a06a48 | 450119a0-c15b-4cc8-a3d8-cc52916d137f |
| medical-policies / Query | 20:07:59.655Z | a80490b2-1b2d-4ce7-ac85-f8aa84f2d956 | 3e90e274-207c-4b6e-b97a-be1d8a9204e7 |
| vector-search-test / Count | 20:08:04.179Z | 855aee3b-3c13-47a5-9041-b4617c886e6a | fed31fcb-56a9-4827-80de-f8b3e31e1823 |
| vector-search-test / Query | 20:08:26.340Z | e326aeb6-a62e-4c2b-a32d-1b980a9401d6 | 0ab600d4-da36-43f8-845f-346a2b0f028d |

This is not limited to the count operation or one index. JSON and server request
IDs provide stronger correlation evidence, but do not independently prove the
origin of the 500, effective permissions or complete network correctness. The
shared API, identity, service and network path remain possible investigation areas.

**Follow-up (2026-09-15 20:15:30.695Z):** The customer supplied the result of the
single zero-result query comparison on `medical-policies` with API `2024-07-01`.
It also returned HTTP 500, `application/json`, CLI exit 1, CLI `2.90.0` and
`NONE_RECOGNIZED`. Client request ID: `6811c779-e016-4138-b51a-54d4d9629e92`;
server request ID: `431476e0-c239-4ccd-af37-d8caae7927d2`.

The failure is therefore not exclusive to `2026-04-01`; the older API is not a
working alternative. Root cause remains unknown, and these summaries do not
establish an outage affecting every caller or index. **Stop repeating probes and
escalate to the Search service owner/Microsoft support** with all five requests.
No further executable changes, additional API comparisons, broader permissions,
index recreation or public-network enablement are recommended based on this
evidence. The diagnostic usage instructions below remain reference material,
not a request to repeat the completed checks.

## Start here: compare operations and indexes

Copy **both** [diagnose-access.ps1](diagnose-access.ps1) and the updated
[check-query.ps1](check-query.ps1) to the **same folder on the customer VM**.
No Python packages or further script files are needed. In an already-open
PowerShell window in that folder:

```powershell
& .\diagnose-access.ps1 -Endpoint 'https://YOUR-SERVICE.search.windows.net' -IndexName 'YOUR-APPROVED-INDEX' -ComparisonIndexName 'YOUR-OTHER-APPROVED-INDEX' -ClientId 'YOUR-UAMI-CLIENT-UUID' -ApprovedAzureHost
```

The runner performs **four** read-only checks: Count and Query on each of two
explicitly approved indexes. Omit `-ComparisonIndexName` for two checks on one
index. There is no automatic index discovery or alternate identity. Both names
are validated before any authentication. It stops immediately on local/input,
identity-login or cleanup errors, and exits 4 if any service/query check fails.
No script retry loop or delay is added; CLI internals may perform authentication
or transport activity of their own.

- **Count:** GET the document count, suppressing the value.
- **Query:** POST a fixed `search=*`, `queryType=simple`, `top=0`, `count=false`
  query. This is a read operation, not a write. It asks for **zero documents**,
  does not request vectors, facets, semantic ranking, embeddings or models, and
  supplies no document-permission bypass. The private response is checked for an
  empty `value` array and no error; unexpected/partial responses fail the probe.
- **Correlation:** `SEARCH_CASE` identifies the index, operation and API version.
  `SEARCH_REQUEST` records UTC, a generated client request UUID, server request
  UUID if present, allowlisted response type and HTTP status. These are support
  correlation data, not credentials. Missing server values stay `UNKNOWN`.

Share those summaries plus any `SEARCH_DIAGNOSTICS` and failure lines; do not
share verbose logs or request/response files. Private files are cleaned up after
each probe. A client correlation ID is sent in `x-ms-client-request-id`; the
service owner or Microsoft support can use it with the UTC timestamp and target.

### Local error: parameter `Operation` not found

If `SEARCH_CASE` is followed by `A parameter cannot be found that matches
parameter name 'Operation'`, the runner has started but the companion's parameter
binding failed **before authentication or a Search request**. This normally means
an older [check-query.ps1](check-query.ps1) was left beside the new runner; it is
not a new Azure HTTP 500 or permission failure.

Replace the companion with the **complete updated** [check-query.ps1](check-query.ps1)
in the same VM folder as [diagnose-access.ps1](diagnose-access.ps1), retaining its
exact filename (not a download-renamed copy). The runner resolves it from its own
folder, not from PATH or another working directory. Do not merely add parameter
declarations to the old probe: the corresponding query implementation is needed.
Rerun the same diagnostic command after replacement; no cloud setting changes
are required for this local mismatch.

The updated runner parses the companion's top-level parameter declarations
without executing it. Missing required parameters or invalid/unreadable source
now produce `PROBE_VERSION_MISMATCH` and exit 2 before any comparison, login or
credential-cache creation. This is a compatibility check, not a signature or
integrity check; continue to follow approved script delivery/signing policy.

### Optional API comparison

Only if needed, add `-CompareApiVersions` to compare `2026-04-01` with stable
`2024-07-01`. With two indexes this is at most **eight probes**, not an ongoing
retry or load test. To limit follow-up calls to one operation/index, use:

```powershell
& .\check-query.ps1 -Endpoint 'https://YOUR-SERVICE.search.windows.net' -IndexName 'YOUR-APPROVED-INDEX' -ClientId 'YOUR-UAMI-CLIENT-UUID' -ApprovedAzureHost -Diagnostics -Operation Query -ApiVersion '2024-07-01'
```

This explicit comparison changes only the API used for that diagnostic request.
It is **not an application downgrade** or a recommendation to remove newer index
features. Older APIs may reject indexes/features that need a newer contract.
No content is requested with either version, and no result validates document
permission enforcement, aliases, schema compatibility or full PoC security.

| Result | Next investigation |
| --- | --- |
| Count fails but Query succeeds on the same index/version | Count-specific API/backend behavior; query endpoint access works for the minimal request, not yet full retrieval |
| Both operations fail on one index but succeed on the comparison index | Original index state, supported features or scoped permissions; don't rebuild it automatically |
| Results differ only by API version | API/feature compatibility or version-specific service behavior; retain evidence before deciding application changes |
| 401/403 | Validate actual role coverage, conditions and service authentication/network policy; do not switch to keys |
| Persistent 500 on both operations/indexes | Escalate with case, UTC and request IDs; owner reviews service health and existing data-plane logs/network intermediaries |
| Response type is text/html instead of expected JSON/text | Inspect the approved proxy/gateway path; this is a clue, not proof of origin |

For persistent 500s, have the owner confirm that the resolved IP belongs to the
approved Search private endpoint, check Resource Health/Service Health and inspect
existing Search request logs at the recorded UTC. The Azure Activity Log alone
does not include query details. No Log Analytics workspace has been supplied;
do not assume logs exist or silently provision logging. If needed, open an Azure
support case using the safe correlation information. Keep public access disabled.

## Scope

[check-query.ps1](check-query.ps1) defaults to an explicitly authenticated **GET
document-count request to one approved index**, using API version `2026-04-01`.
`-Operation Query` selects the fixed zero-result read query described above.
The slash-form index route avoids the Windows batch launcher's handling of
unquoted parentheses; the operation and selected target are unchanged.
The service returns only a count; the script suppresses even that value. No
document text, fields, vectors, medical content or tokens are retrieved for
display. No document content is requested at all.

This is not an index-list, schema or service-statistics request. It does not
create/modify/delete indexes or documents, run/reset indexers, change roles or
configuration, invoke embeddings/models, perform semantic/agentic retrieval or
call Foundry IQ knowledge bases. There is no script retry loop. The request
uses Search capacity and may be recorded in service logs; ordinary service
pricing applies. It does not incur OpenAI inference from this probe.

Success proves only that the selected identity can perform the selected read on the
selected index from this VM. It does **not** verify schemas, analyzers, aliases,
vector/semantic retrieval, document-level authorization, PoC filters/content,
index creation permissions, other indexes or Python SDK compatibility. An empty
index is a valid successful result.

## Prerequisites

- Run on the approved **customer Azure Windows VM**, not the separate workstation.
  Use PowerShell 5.1/7 and the installed Azure CLI; no Python/PoC packages needed.
- The supplied **user-assigned identity client ID** must belong to an identity
  attached to that VM and authorized to query the selected index. All trusted
  VM users can potentially use the attached identities.
- Search must accept Entra/RBAC data-plane authentication (**Role-based access
  control** or **Both**). The usual minimum query role is **Search Index Data
  Reader**, scoped to the approved index where appropriate. A control-plane
  Reader/Contributor role is not equivalent, and neither App Configuration nor
  OpenAI roles confer Search access. The probe does not set authentication mode
  or assign roles; an authorized administrator must review any required change.
- IMDS and the HTTPS Search endpoint must be reachable using approved private
  DNS, routing, proxy and CA settings. Use the normal `*.search.windows.net`
  hostname even with private endpoints. Do not enable public access, disable
  certificate checks or bypass document permissions to make the probe pass.
- Deliver only the standalone script, following the customer's signing policy.
  Run with `&` from an already-open PowerShell window; never dot-source it or use
  an execution-policy bypass.

From the repository root on the VM, substitute approved nonsecret values:

```powershell
& .\deployment\search\check-query.ps1 -Endpoint 'https://YOUR-SERVICE.search.windows.net' -IndexName 'YOUR-INDEX' -ClientId 'YOUR-UAMI-CLIENT-UUID' -ApprovedAzureHost
```

`-ApprovedAzureHost` acknowledges the approved host, identity and selected target;
it is not a grant of access. Invalid input/missing approval stops before login.
Use one exact approved existing index name, not a guessed name from the repo.
The earlier probes did not leave an identity signed in: this script establishes
its own explicit MI login and uses the Search token audience internally in CLI.
It never puts a token in PowerShell variables, arguments, request files or output.

Before login, a fresh temporary cache parent is restricted to the current
Windows identity and SYSTEM. This does not isolate it from VM administrators.
Existing CA/proxy settings are retained; IMDS and loopback are appended to proxy
bypasses. Caller environment settings are restored and private CLI cache/error
files removed in `finally`, without changing the caller's normal CLI sign-in.
A crash or uncatchable termination can prevent cleanup; honor customer policy
for credential caches and have authorized administrators handle any remnants.

## Results

Console-only summaries are safe to share. Do not share raw CLI diagnostics,
credential caches or document exports. The actual document count is not printed.

### Unclassified failure: safe diagnostic mode

Copy the updated script to the VM and add `-Diagnostics` to the same invocation:

```powershell
& .\deployment\search\check-query.ps1 -Endpoint 'https://YOUR-SERVICE.search.windows.net' -IndexName 'YOUR-INDEX' -ClientId 'YOUR-UAMI-CLIENT-UUID' -ApprovedAzureHost -Diagnostics
```

This still sends just one count request to the same index. It enables CLI verbose
logging for that request **only inside the protected temporary directory**, not
on the console, and removes those logs with the cache. It does not use `--debug`.
On failure, a local CLI version command runs inside the same private environment.
The extra `SEARCH_DIAGNOSTICS` summary contains only the numeric CLI exit code,
HTTP response status if present, a fixed error-kind category and a validated
CLI version. `SEARCH_REQUEST` adds the bounded correlation information described
above on both successful and failed requests. Raw headers, URLs, error messages, paths, tokens and counts are never
included in that summary; do not share the private logs.

`http_status=UNKNOWN` means no recognizable response status was captured, not
proof that Search was unreachable. A recorded HTTP 2xx with a nonzero CLI exit
can indicate a CLI processing problem; it is **not** reported as a passed probe.
The count API returns a scalar integer, unlike the object returned by the OpenAI
check, but the reported `SHELL_SYNTAX` is a separate, reproduced launcher failure,
not evidence of scalar-response processing. Do not change API versions, switch
indexes or broaden roles based solely on the original generic error. If all
diagnostics remain unknown after using the corrected script, the authorized
operator must investigate locally using approved secure tooling.

| Exit | Meaning |
| --- | --- |
| 0 | `SEARCH_READ_SUCCEEDED` for Count or `SEARCH_QUERY_SUCCEEDED` for Query. |
| 2 | Invalid input, missing approval/CLI, incompatible runner companion or local secure-cache/probe error. |
| 3 | Identity sign-in failed; no Search request was attempted. |
| 4 | Read request failed or query response was unexpected; inspect the fixed category. |
| 5 | Private-cache cleanup failed; arrange secure local cleanup. |

- **403:** check data-read scope/propagation, service authentication mode and
  network restrictions. It is not proof a broader role is required.
- **401:** check the selected identity, tenant, Search token audience and RBAC mode.
- **404:** check the exact index name/endpoint and API compatibility; no automatic
  index creation or alternate-index probing.
- **429:** check capacity/rate limits without repeatedly retrying.
- **DNS/TLS/timeout:** fix approved connectivity/trust, not roles.
- **400:** check CLI/API and index policy, including any document permission
  requirements. Do not disable those protections or elevate access for this test.
- **5xx:** check service health with the owner; role changes do not fix server errors.
- **CLI processing/invocation:** use the safe metadata to investigate local CLI
  behavior separately from Search authorization.

### HTTP 500: bounded comparison, not reconfiguration

The customer has completed both the bounded comparison and the single older-API
query follow-up, all with HTTP 500. Use the recorded evidence for escalation,
rather than repeating either check.
Have the service owner inspect Resource Health/Service Health, existing Search
resource logs if configured, and the approved private-network path. The customer
has confirmed the expected inherited Search data role in Check access; record
that as completed rather than requesting another role grant. If authorization
handling is implicated by support traces, investigate the specific finding.

Built-in Search metrics are available without a Log Analytics workspace, although
they do not expose the underlying exception. Detailed query logs need an existing
diagnostic destination; enabling one now does not recover earlier query logs.
Activity Log alone does not contain data-plane request details. Absence of a Log
Analytics workspace does not prevent opening a support case with the resource,
UTC timestamps and client/server request IDs. A healthy resource status does not
rule out a request-specific service issue.

Do not repeatedly retry, create/rebuild indexes, silently change application API
versions, broaden roles or disable document/network protections to make this
diagnostic pass. No further executable changes or Azure mutations have been made
in response to these five failed requests.

## After access succeeds

Separately review schemas/field attributes, filters, language analyzers and approved
content before deciding whether these indexes can back either PoC. A vector index
name alone does not establish compatibility. PoC 002 includes translation-status
filtering that an unrelated existing index might not support. Do not patch/rebuild
customer indexes or run the legacy setup scripts unchanged. If dedicated demo
indexes are needed, agree isolated names, capacity and approved seed content first.

## Offline tests

The suites below use a harmless local batch launcher and handler, not Azure CLI,
IMDS or Search. The launcher forwards arguments inside a parenthesized IF/ELSE
block so the tests exercise shell parsing, not just raw argument logging.
They need Windows PowerShell but no Pester, Python or cloud credentials:

```powershell
& .\deployment\appconfig\tests\test-check-access.ps1 -ProbePath (Join-Path $PWD 'deployment\search\check-query.ps1')
& .\deployment\search\tests\test-check-query.ps1
```

They verify native exit codes, input/host gates, the literal `$count` route and
Search audience, no content retrieval/mutations, private ACLs, output suppression,
empty-index success, failure categories, no retry escalation, environment
restoration and cleanup. A regression test reproduces the former URL's shell
exit 255 without reaching the handler, then the full probe suite exercises the
corrected route through that same launcher. Passing them does not establish live
Search access.

On 2026-09-14, the native-wrapper and mocked Search suites, including the new
safe-diagnostics, status-extraction and redaction cases, passed in local Windows
PowerShell 5.1. The full suite also passed through the launcher-shaped fixture
after reproducing the former URL's exit 255 and switching to the slash route.
The customer's follow-ups diagnosed the shell failure and then reported HTTP
500 on the corrected route; successful Search access and PowerShell 7 execution remain
unverified. No real Azure CLI, IMDS or Search requests were made by these tests
or the assistant. The existing App Configuration and OpenAI probes were not modified.

On 2026-09-15, the expanded offline suites passed in local Windows PowerShell 5.1:
fixed top=0 query/body forwarding, both explicit API versions, rejection of
nonempty/error/malformed/observed-partial responses, correlation redaction and
the bounded runner (two/four/eight checks, mixed-result failure and early stop).
The customer-VM comparison has not been run by the assistant. The customer later
supplied the live query success recorded above; PowerShell 7 execution remains
unverified.

References: [Count documents](https://learn.microsoft.com/rest/api/searchservice/documents/count?view=rest-searchservice-2026-04-01),
[Document-operation URL format](https://learn.microsoft.com/rest/api/searchservice/#key-concepts),
[Search roles](https://learn.microsoft.com/azure/search/search-security-rbac),
[Search Documents](https://learn.microsoft.com/rest/api/searchservice/documents/search-post?view=rest-searchservice-2026-04-01),
[Azure CLI REST requests](https://learn.microsoft.com/cli/azure/reference-index#az-rest).