# Windows VM: PoC 001 comparison

Run the baseline/candidate comparison on approved Azure Windows compute with
**one existing user-assigned managed identity** and a GPT-4o deployment. The
browser runs **on the VM** at <http://127.0.0.1:8501>. This is a foreground,
localhost-only milestone, not persistent hosting or a shared HTTPS endpoint.

**Current access decision, 2026-09-17:** users sign into the VM through its
existing approved access route and use the browser locally. Shared networking
and HTTPS are deferred; section 7 preserves the administrator handoff for future
use. The optional live configuration editor below uses the same managed identity.

The [launcher](run.py) starts either the Streamlit UI or its internal A2A agent.
It does not install packages, request tokens during validation, change Azure,
seed configuration, configure services, change firewalls or expose public ports.
Python 3.10+ is required. The current Windows Server 2025 VM has Python 3.14.7;
dependency installation and offline tests must pass on the actual target host.

## Scope and identity boundary

- `ELV_DEMO_MODE=comparison` is an explicit PoC001-only policy. It uses only
  `ELV_MI_APP_CLIENT_ID` and requires `ELV_HOSTING_MODE=azure-vm`. Unknown modes
  and missing/malformed client IDs fail closed. No developer-login fallback,
  app-registration secret, dotenv or persona credential file is used.
- Comparison retains responses, metrics, configuration refresh, A2A provenance
  and local synthetic feedback. Configuration editing is off by default. The
  explicit `ELV_ENABLE_CONFIG_EDITING=true` option adds a bounded live editor
  for existing baseline/candidate settings. `ELV_ENABLE_RAG=true` separately
  enables approved-index retrieval and knowledge configuration. Both options are
  off by default. Persona switching, publishing, permission probes, draft reads,
  audit and unrestricted writes remain disabled. These are local application
  restrictions, **not Azure RBAC denials**.
- This does not reduce the existing identity's Azure permissions. All trusted
  VM users/code can potentially use attached identities. Separate Windows
  accounts are not managed-identity isolation. Do not host untrusted workloads.
- The default `full` mode and the [Red Hat deployment](../redhat/README.md)
  retain their five-distinct-identity governance contract. One identity must
  never be substituted into all five settings. PoC002 is unchanged.
- Use synthetic questions only; never enter patient/personal data. On 2026-09-18
  the user approved all documents in `medical-policies-vector` for retrieval and
  excerpt transmission to the existing Azure OpenAI deployment. Other indexes
  require separate approval. Do not copy old secrets, token caches, virtual
  environments or feedback. All local users share the approved retrieval scope.

## 1. Azure team preparation

The approved operator must confirm the runtime UUID is the **Client ID** of
the identity attached under **VM > Identity > User assigned**, not its
Object/Principal ID or an app-registration Secret ID. No client secret is needed.

The comparison needs the existing production App Configuration store and Azure
OpenAI account/deployment; optional RAG also needs the approved Search index.
Confirm effective access at these resources:

| Resource | Minimum intended runtime permission |
| --- | --- |
| Approved PoC App Configuration store | App Configuration Data Reader for comparisons; Data Owner for live editing |
| Approved Azure OpenAI account | Cognitive Services OpenAI User |
| Approved Search index, when RAG is enabled | Search Index Data Reader, or existing sufficient data-query permission |

Existing Data Owner access already includes configuration reads; do not add
redundant roles, broaden permissions or revoke shared assignments automatically.
Identity attachment/role changes require the Azure team's approval, not merely
local Windows administrator rights. The VM also needs IMDS and HTTPS access to
these services through approved private DNS, proxy and CA configuration.

### Populate the empty store

**This is an Azure write requiring separate approval.** In the approved store's
**Configuration explorer**, add these 12 key/label combinations. Recheck that
each target is absent and stop on a collision rather than overwrite existing
values. Use the platform team's authorized sign-in; runtime read access does
not authorize seeding. No new service, draft store or extra identity is required
for this comparison milestone.

| Key | Value with label `baseline` | Value with label `candidate` |
| --- | --- | --- |
| `experience:persona` | a Contoso customer support agent | a caring Contoso customer support specialist |
| `experience:tone` | neutral and professional | warm, friendly, and empathetic |
| `experience:verbosity` | brief | concise but complete |
| `experience:reading_level` | grade 9 | grade 6 |
| `experience:response_structure` | a single short paragraph | a one-sentence acknowledgement, then 2 to 3 short bullet points, then a clear next step |
| `experience:prompt_asset` | response:v1 | response:v2 |

These synthetic values come from the existing
[seed reference](../../pocs/001-config-driven-responses/scripts/seed-config.ps1).
Do **not** run the original setup/governance/knowledge/seed/teardown scripts
unchanged against customer services. They can overwrite settings or provision
and delete resources. No `knowledge:*` entries are needed for an ungrounded
comparison; the RAG setup below initializes them separately.

### Explicit initializer

The separate [initializer](initialize_config.py) can perform the approved
one-time preparation using the identity in the external runtime JSON. That
identity needs **App Configuration Data Owner** for this operation; normal
comparison requests only require data-read access. It is never run by startup.

After preparing the venv and runtime JSON below, preview from the repository root:

```powershell
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe .\deployment\windows\initialize_config.py --config C:\ProgramData\elv\poc001\runtime.json
```

The default preview reads local files only. It displays the target endpoint and
the 12 proposed synthetic settings from the existing prompt samples. It does not
request a token, inspect the Azure store or write anything to Azure.

**Only after explicit approval for those writes**, apply on the approved VM:

```powershell
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe .\deployment\windows\initialize_config.py --config C:\ProgramData\elv\poc001\runtime.json --apply --approved-azure-host
```

The initializer selects the managed identity explicitly, checks all 12 exact
key/label pairs before writing, preserves matching entries, and stops before
writing if any existing value differs. Missing entries use the SDK's atomic
create-only operation, so a concurrent writer cannot be overwritten. A race
with different content stops the run. Readback verifies all 12 desired values.
Existing Azure values, credentials and raw SDK errors are not printed.

This is not a transaction: after a network/permission failure, earlier creates
may remain. There is no deletion, rollback or application retry loop. Review the
failure and rerun only after resolving it; matching entries will be preserved.
No other keys, labels, resources, roles, indexes or deployments are changed.

After intentionally editing a profile, do not rerun the initializer to reset it.
It will report conflicts with changed sample values rather than overwrite them.

After `INITIALIZATION_SUCCEEDED`, select **Refresh configuration from Azure**
in the UI and then **Generate side-by-side comparison**. No app restart is needed.

The app deliberately reports an empty profile as a preparation gap; it does not
invent local defaults or present them as configuration read from Azure.

## 2. Prepare the Windows environment

Use an approved source-only checkout on the VM. Keep the source and dependencies
writable only by trusted deployment operators. Use the existing approved package
mirror, TLS trust and proxy settings. Do not disable verification or bypass
PowerShell execution/signing policy.

For a fresh checkout, from its root in Windows PowerShell 5.1 or PowerShell 7:

```powershell
py --list-paths
py -3.14 -m venv .\pocs\001-config-driven-responses\.venv
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe -m pip install -r .\pocs\001-config-driven-responses\requirements.txt
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe -m pip check
```

Substitute an approved installed interpreter if needed. If dependencies do not
support Python 3.14 on another VM, arrange an approved Python 3.12 side-by-side
installation; do not replace system Python or force incompatible packages.
Stop existing components before changing their environment. Do not overwrite an
existing virtual environment without reviewing its ownership and purpose.

Text readability metrics use `textstat` and its NLTK pronunciation data. If the
approved environment needs that corpus installed in advance, run the following
with the same Windows account that will run the UI, through approved download
routes (or have the administrator deliver the corpus):

```powershell
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe -m nltk.downloader cmudict
```

## 3. External nonsecret configuration

Use `C:\ProgramData\elv\poc001\runtime.json` and a separate writable
`C:\ProgramData\elv\poc001\state` directory. The launcher rejects JSON/state
inside the checkout, unexpected keys, duplicate keys, credential-bearing URLs,
missing settings and inherited secret/certificate/federation credentials.

Have the authorized Windows operator create a new private directory. If it
already exists, inspect it rather than replacing its ACLs or contents. This
example grants access only to the current operator, SYSTEM and Administrators:

```powershell
$runtimeDirectory = Join-Path $env:ProgramData 'elv\poc001'
if (Test-Path $runtimeDirectory) { throw 'Directory exists: review existing configuration and permissions first.' }
New-Item -ItemType Directory -Path $runtimeDirectory -ErrorAction Stop | Out-Null
$operatorSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
icacls $runtimeDirectory /inheritance:r /grant:r "*${operatorSid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'
if ($LASTEXITCODE -ne 0) { throw 'Cannot establish private runtime permissions.' }
New-Item -ItemType Directory -Path (Join-Path $runtimeDirectory 'state') -ErrorAction Stop | Out-Null
```

Use an approved editor to populate `runtime.json` with **only nonsecret values**:

```json
{
  "AZURE_APPCONFIG_ENDPOINT": "https://YOUR-STORE.azconfig.io",
  "AZURE_OPENAI_ENDPOINT": "https://YOUR-ACCOUNT.openai.azure.com/",
  "AZURE_OPENAI_DEPLOYMENT": "YOUR-EXISTING-DEPLOYMENT-NAME",
  "AZURE_OPENAI_API_VERSION": "2024-10-21",
  "ELV_MI_APP_CLIENT_ID": "YOUR-VM-MANAGED-IDENTITY-CLIENT-UUID",
  "ELV_OPENAI_REQUEST_PROFILE": "gpt4o",
  "ELV_ENABLE_CONFIG_EDITING": "true",
  "ELV_STATE_DIRECTORY": "C:/ProgramData/elv/poc001/state"
}
```

The account endpoint is not a Foundry project URL; the deployment name may differ
from the model name. `gpt4o` uses `max_tokens` and omits reasoning-only controls
from the existing prompt assets. Outside this launcher, the default `asset`
request profile preserves the original reasoning-model contract.

`ELV_ENABLE_CONFIG_EDITING` accepts the strings `"true"` or `"false"`. Omit it
or set `"false"` to retain the read-only comparison UI. An inherited environment
variable cannot turn it on when runtime JSON omits it. The setting is under the
Windows operator's control, not a browser toggle. Enabling it requires write
permission on the existing PoC store; no additional identity or draft store is
needed. Restart the UI after changing this option. The existing agent can keep
running when only this UI option changes.

The launcher forces comparison/VM mode and the loopback A2A endpoint regardless
of inherited mode/host settings. It preserves CA/proxy settings and appends
IMDS/loopback bypasses to `NO_PROXY`. Configuring a tenant ID is not a way to move
an identity between tenants. Restart both components after changing endpoints,
identity or model settings; credentials are process-level, not browser-selectable.
RAG opt-in, Search endpoint and approved-index changes also require both
components to restart. The launcher clears inherited Search settings when they
are omitted from runtime JSON; they cannot silently enable retrieval.

## 4. Offline checks

Use the PoC working directory for its tests. Azure/model clients are mocked;
no tokens, customer content or configuration writes are needed:

```powershell
Push-Location .\pocs\001-config-driven-responses
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
Pop-Location
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe -m unittest discover -s deployment\redhat\tests -p test_hosting.py -v
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe -m pip check
```

The shared `test_hosting.py` is cross-platform; this does not execute the Linux
installer or establish systemd behavior. Stop if any check fails. Record the
resolved packages as deployment evidence, not a pre-existing reproducible lock:

```powershell
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe -m pip freeze --all | Out-File -Encoding utf8 .\pocs\001-config-driven-responses\.installed-requirements.txt
```

Validate the runtime file without starting either component or requesting a token:

```powershell
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe .\deployment\windows\run.py --component agent --config C:\ProgramData\elv\poc001\runtime.json --approved-azure-host --validate-only
```

`CONFIGURATION_VALID` proves local syntax/settings validation only, not identity
attachment, effective roles, populated profiles or Azure connectivity. The
acknowledgement flag confirms operator approval of the execution host; it grants
no permissions and is not an Azure attestation check.

## 5. Start and view locally

Keep these two non-elevated terminal sessions open on the VM, both at the
repository root. Check that ports 8501 and 9999 are available first; do not kill
unrelated listeners. No RDP, NSG or firewall changes are needed for localhost.

Terminal 1, internal A2A agent:

```powershell
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe .\deployment\windows\run.py --component agent --config C:\ProgramData\elv\poc001\runtime.json --approved-azure-host
```

Terminal 2, comparison UI:

```powershell
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe .\deployment\windows\run.py --component ui --config C:\ProgramData\elv\poc001\runtime.json --approved-azure-host
```

In another VM terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:9999/health -TimeoutSec 10
Invoke-RestMethod http://127.0.0.1:8501/_stcore/health -TimeoutSec 10
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 8501, 9999 } | Select-Object LocalAddress, LocalPort, OwningProcess
```

Both listeners must be **127.0.0.1 only**. Open <http://127.0.0.1:8501> in the
VM's browser. Opening the UI/health endpoints does not verify Azure access.

After the approved profiles are present, generate the supplied synthetic
customer-message comparison. Verify two visible GPT-4o answers, baseline and
candidate profile provenance, the selected prompt assets and metrics. Each click
makes two normal inference requests and consumes quota/billable tokens; do not
run a load loop. Preference buttons write synthetic messages and choices to
`state/feedback.csv`; retain only approved demonstration evidence.

After an approved platform-team configuration change, refresh and regenerate.
New contexts must observe the changed profile without a code release. Confirm
there is no persona selector, governance or audit tab. Grounded comparisons and
source citations are available only with the explicit RAG setup below. Neither
mode claims separate-persona role isolation or audit acceptance.

### Edit live configuration from the UI

With `ELV_ENABLE_CONFIG_EDITING=true`, the app shows **Experience comparison**
and **Configuration** tabs. The original multi-persona Governance tab is not
restored: every edit uses the existing runtime managed identity and directly
changes the selected profile in the production store.

1. Open **Configuration** and choose **Profile** (`candidate` by default, or
  `baseline`) and one of the six `experience:*` settings. When RAG is enabled,
  **Configuration area** selects **Experience** or **Knowledge**.
2. Select **Load current value**. This reads the exact existing key/label and its
  Azure ETag; selecting another profile or setting requires loading that target.
  Loading again discards unsaved edits and replaces them with the current value.
3. Edit **New value**, or choose `response:v1`/`response:v2` for **Prompt asset**.
  Only nonempty values up to 2,000 characters and the supported prompt assets
  are accepted. Do not put secrets or customer data in experience settings.
4. Select **Save to Azure** to update that one live value. There is no draft,
  publishing or approval step. Loading/viewing the editor never writes values.
  Existing tags/content type are preserved, and the SDK uses the loaded ETag
  to reject concurrent changes. Missing settings are not created. A conflict
  requires reloading and reviewing the latest value before another save.
5. Return to **Experience comparison** and generate again. A successful save
  clears the editing session's cached results and A2A context IDs, so the next
  requests resolve current Azure configuration without a server restart. Other
  open sessions must select **Refresh configuration from Azure** to leave their
  pinned contexts. Saving alone does not invoke the model.

All trusted VM users share this configuration and identity; it is not per-user
Azure authorization. Generic writes, new keys, deletion, other labels/prefixes,
Search index/document writes, audit and draft publishing are not exposed by this
editor. No Azure values are automatically changed by enabling or starting it.

### Ground responses with an existing Search index

The implemented first integration reuses **`medical-policies-vector`** on
`https://tenxeng-benefit-ai-search.search.windows.net`, with the same VM managed
identity. It performs **simple keyword retrieval**, not vector similarity,
hybrid retrieval or semantic ranking. `ContentVector` (1,536 dimensions) is left
untouched and is not queried. No embedding deployment, new index, schema change,
indexer run, document upload or reindexing is required for this text path.

On 2026-09-18, a schema GET returned 403; no role was broadened. The user supplied
the field names. Bounded zero-document queries then verified the selected fields
and `Status`/`State` filters, and a live approved RAG comparison returned both
answers with three retrieved source citations each. Schema-read permission is
not a prerequisite for this configured runtime query path.

**Configuration and tags are different layers:**

- App Configuration keys such as `knowledge:index` and `knowledge:filter` are
  stored under the `baseline` and `candidate` **labels**, independently.
- Search fields such as `Status` and `State` are metadata on each indexed
  document/chunk. An OData filter uses these exact, case-sensitive field names
  and their existing values; Azure resource tags and App Configuration tags are
  not automatically Search document filters.
- Changing an existing filter or field mapping changes retrieval on the next
  refreshed context without reindexing. Adding a new document tag/field or making
  an unavailable field filterable is a separate Search/indexing change requiring
  owner review; this application does not perform it.

Add these settings to the existing external runtime JSON (keep the other runtime
settings; do not replace the whole file with this fragment):

```json
{
  "ELV_ENABLE_RAG": "true",
  "AZURE_SEARCH_ENDPOINT": "https://tenxeng-benefit-ai-search.search.windows.net",
  "ELV_SEARCH_ALLOWED_INDEXES": "medical-policies-vector"
}
```

The allowlist is an operator-controlled, comma-separated list of approved exact
index names. Changing `knowledge:index` cannot select a name outside that list.
It is not a substitute for Azure RBAC or a document-level authorization system.
`ELV_ENABLE_RAG` defaults to `"false"`; invalid values fail closed.

Prepare the following local profile in the same protected external directory,
for example `C:\ProgramData\elv\poc001\knowledge.json`. Its keys are unprefixed;
the initializer adds `knowledge:` and creates them under **both** profile labels:

```json
{
  "enabled": "true",
  "index": "medical-policies-vector",
  "filter": "",
  "top_k": "3",
  "query_mode": "simple",
  "citation_style": "inline",
  "title_field": "Title",
  "content_field": "Content",
  "url_field": "",
  "industry_field": "",
  "audience_field": "",
  "status_field": "Status",
  "effective_date_field": "PublishDate",
  "state_field": "State",
  "source_field": "BlobName",
  "search_fields": "Title,Content"
}
```

The mapping uses `Content` as the excerpt, `Title` as the citation title,
`BlobName` as the source identifier, and `PublishDate` as the displayed effective
metadata. Empty optional mappings deliberately omit absent sample fields such as
`url`, `industry` and `audience`. `BlobName` is not assumed to be a public URL;
the app does not generate signed Blob links. `LastReviewDate`, `Description`,
`Guideline`, `id`, `ChunkId` and vector data are not needed by this initial mapping.

Preview the **32 knowledge entries only** (16 per label):

```powershell
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe .\deployment\windows\initialize_config.py --config C:\ProgramData\elv\poc001\runtime.json --knowledge-config C:\ProgramData\elv\poc001\knowledge.json
```

After explicit approval, apply with the same create-only safeguards:

```powershell
& .\pocs\001-config-driven-responses\.venv\Scripts\python.exe .\deployment\windows\initialize_config.py --config C:\ProgramData\elv\poc001\runtime.json --knowledge-config C:\ProgramData\elv\poc001\knowledge.json --apply --approved-azure-host
```

With `--knowledge-config`, existing `experience:*` values are not touched. The
initializer never writes to Search. It preserves matching entries and stops on
conflicts; prior successful creates can remain after a failure. Do not rerun the
initializer to undo intentional knowledge edits. The approved 2026-09-18 run
created and verified all 32 entries. Both labels initially have an empty filter
because the user approved the entire selected index, not just one status/state.

Restart both components for the runtime opt-in, reload the browser, enable
**Ground with AI Search**, and submit a synthetic policy question. Each comparison
performs two retrievals/model requests, one per profile. The initial maximum is
three returned chunks per request, truncated to 2,500 characters each; `top_k`
can be set from 1 to 20. Titles/status/state/source identifiers accompany numbered
citations. Retrieved excerpts and rendered prompts stay inside the agent rather
than being included as raw A2A artifacts. Source citations show retrieved
evidence; they do not independently certify the model's factual accuracy.

#### Filter examples using existing metadata

Bounded facet inspection returned `Status` values `Reviewed`, `Revised`, and
`New`. `State` values included `NY`, `CA`, `VA`, `CO`, `CT`, `GA`, `IN`, `KY`, `ME`,
`MO`, `NH`, `NV`, `OH`, `WI`, and **`medical-policies`**. The last value is not a
state code; ask the content owner what it means rather than treating it as a
geographic scope. These values can change as the index content changes.

Examples for **Configuration > Knowledge > filter**, after selecting a profile
and loading its current value:

```text
State eq 'NY'
Status eq 'Reviewed'
State eq 'CA' and (Status eq 'Reviewed' or Status eq 'Revised')
```

These are examples, not automatically applied rules. `Reviewed` does not mean
the application has independently verified content approval. A blank filter is
permitted for the user-approved whole index. An invalid/nonmatching filter is
never removed to widen retrieval: invalid queries fail and no matching text
returns a no-sources message **without a model call**. A grounded request for a
profile with `knowledge:enabled=false` is rejected rather than silently falling
back to an ungrounded answer. Only `simple` query mode is enabled for this
existing-index comparison; semantic/vector/hybrid options require separate work.

Select **Save to Azure** to change one existing knowledge value with ETag
protection. The saving session's results and contexts are cleared; other open
sessions need **Refresh configuration from Azure**. Switching the grounding
toggle also starts fresh contexts. The original `experience:prompt_asset`
selection still controls ungrounded replies; grounded replies use
`response:v3` plus that profile's experience settings and knowledge scope.

To pause RAG without deleting anything, set `ELV_ENABLE_RAG` to `"false"` in
runtime JSON and restart both components. Search content, vectors, and saved
knowledge configuration remain intact. Networking/HTTPS stays deferred.

## 6. Stop and troubleshoot

Press Ctrl+C in each component's terminal. These are foreground processes, not
Windows services; sign-out/reboot recovery is not implemented. Before updating,
stop both, retain approved configuration/state and the prior dependency inventory,
then validate again. Rollback uses the prior reviewed source and matching
dependencies, not recreation of shared Azure resources.

- Configuration error: correct the named nonsecret JSON setting. Never replace
  a missing managed identity with an app-registration secret or `az login`.
- Empty profiles: ask the Azure team to populate the 12 approved entries above.
  A successful access probe against an empty store is not demonstration readiness.
- Configuration tab absent: verify `ELV_ENABLE_CONFIG_EDITING` is `"true"` in
  runtime JSON, restart only the UI, and reload the browser page.
- Save conflict: another editor changed or removed the setting. Load its latest
  value and review before saving; do not bypass the ETag check or reinitialize.
- 401/authentication: verify Client ID, VM attachment and tenant placement.
- 403: verify actual identity/role scope and network policy separately. Do not
  add broad roles merely to suppress a failure.
- DNS/TLS/timeout: repair approved private DNS, routing, proxy bypass and CA trust;
  do not disable TLS verification or enable public resource access.
- Model 400: verify this deployment is GPT-4o and `gpt4o` request profile is active.
  Deployment names are not used to guess model capabilities.
- 429: review deployment quota with the owner, without automatic repeated calls.
- Metrics corpus/download error: arrange approved NLTK `cmudict` installation
  for the UI account, not a TLS-bypass workaround.
- Grounding toggle absent: confirm `ELV_ENABLE_RAG` is `"true"` and the approved
  Search endpoint/index list is populated in runtime JSON, then restart both
  components. Do not enable it solely through inherited environment variables.
- Search 400: check exact field casing, retrievability/searchability, filter
  syntax and `query_mode=simple`. Do not delete the filter or switch indexes as
  a silent fallback. The initial field capability checks were read-only.
- No source text: verify the selected profile's knowledge mappings and filter.
  No model is called for an empty retrieval in comparison mode. Do not infer
  that the whole index is empty just from one question/filter.

## 7. Shared private HTTPS: administrator handoff

**Status, 2026-09-17: deferred by the customer; future reference only.** Users
will sign into the VM and view/edit the PoC locally. Do not perform the network,
DNS, certificate, IIS or firewall steps below as part of the current work.
Localhost response generation is working; shared access and persistent hosting
have not been configured or validated for this PoC.

The earlier proposed source scope was the **whole `vnet-dig-gld-eastus2` VNet**.
That design is retained below, not implemented. If this work resumes, reconfirm
the scope, current VNet prefixes, DNS/certificate ownership and required change
approvals before applying it. The networking prerequisites do not block local
VM viewing or the live configuration editor.

Reassess editor access before any future shared publishing. When
`ELV_ENABLE_CONFIG_EDITING=true`, every client admitted to the UI can edit these
live settings, not just generate comparisons. The original whole-VNet proposal
predated the editor; it is not a substitute for reviewing that new capability.

The agreed candidate address is
`https://tenxbenaiwinvm.us.ad.wellpoint.com`, subject to approval of private DNS,
certificate reuse and browser trust. This replaces the earlier private-IP URL
preference. An installed Server Authentication certificate covers that DNS name,
not the IP. Do not use `https://10.134.64.159` with that certificate or bypass
certificate warnings.

### Known target and missing network details

| Item | Value / evidence |
| --- | --- |
| VM | `tenxeng-benefit-ai-windows-virtual-machine` |
| VM resource group | `apm1081142-gld-dtpqa-01-rg` |
| VM subscription | `20659eb6-9c76-49ae-9f30-7c478bb5244d` |
| VNet | `vnet-dig-gld-eastus2`, supplied by the user; VNet resource group and subnet association need administrator confirmation |
| VM private address | `10.134.64.159` |
| Locally observed subnet | `10.134.64.0/19`; one subnet, not the full VNet address-space inventory |
| Existing IIS | W3SVC/WAS running; port 80 already in use. Preserve existing sites and bindings. |
| UI upstream | `http://127.0.0.1:8501` |
| Internal agent | `http://127.0.0.1:9999`; never proxy or expose it to viewers |
| Approved source scope | All address-space CIDRs configured on `vnet-dig-gld-eastus2`; exact prefixes pending administrator inventory |
| Intended audience | Clients using those VNet source addresses, without browser sign-in; network restrictions are the viewer access control |

This whole-VNet scope replaces the earlier narrow viewer-subnet proposal. All
clients within the allowed source ranges can use the comparison UI and incur
model usage; continue using synthetic data only. It does not automatically
include peered VNets, on-premises networks, VPN client pools or internet sources.
Clients using those routes need separately approved source ranges unless their
traffic is translated into an allowed range. Review any such NAT/proxy behavior
because IP-based rules cannot distinguish the original caller behind it.

The user cannot view the subnet. The runtime managed identity also received HTTP
403 on a VM management read; discovery stopped. Application data-plane access
does not imply network-management access. The Azure/network administrator should
perform the inventory using their authorized account; do not grant the runtime
identity broader roles just to discover networks. The VNet may be in a different
resource group from the VM.

### Administrator steps

1. **Identify the network boundary.** In Azure Portal, open the VM, then
  **Networking > Network settings > network interface > IP configurations >
  primary configuration**. Record the actual subnet resource ID, name and CIDR,
  associated VNet, NIC/subnet NSGs, route table and private-IP allocation.
  Confirm the VNet association against `vnet-dig-gld-eastus2`. If the IP is
  dynamic, agree how its stability and DNS will be maintained; make any allocation
  change only through the approved Azure NIC configuration process.

2. **Retrieve the approved VNet's full address space.** Open **Virtual networks >
  vnet-dig-gld-eastus2 > Settings > Address space** in the correct subscription
  and resource group. Return all configured source CIDRs, not just the VM's
  subnet, for the whole-VNet HTTPS rule. The administrator does not need to select
  a smaller viewer subnet or grant the runtime identity network-read rights.
  Review the actual route, NAT/proxy behavior and a test client in that VNet.
  Use the explicit VNet address prefixes, not the Azure `VirtualNetwork` service
  tag: that tag can include peered VNets, connected on-premises ranges and other
  routing-derived prefixes, exceeding this approval. Do not substitute all
  RFC1918 ranges, `Any`, or the single observed `10.134.64.0/19` subnet for the
  confirmed full address space. Keep the recorded CIDRs under change control
  if the VNet address space changes later.

3. **Confirm private DNS and TLS.** Verify the agreed hostname resolves to
  `10.134.64.159` from the intended VNet clients, including required
  private DNS forwarding. Obtain the certificate owner's approval to reuse the
  installed certificate. Check its validity, Server Authentication usage, name,
  private-key availability, full issuing chain, client trust and renewal owner.
  Do not export/share the private key. No public IP, public DNS publication or
  public application endpoint is needed. If the hostname cannot be approved,
  agree a replacement name and matching trusted certificate before proceeding.

4. **Review existing IIS in an elevated administrator session.** Inventory and
  back up the relevant sites, application pools, bindings and proxy settings.
  Check IIS WebSocket support and approved installations of URL Rewrite and
  Application Request Routing (ARR). The earlier unelevated registry/config
  checks did not prove these extensions are installed or absent. Install only
  approved, supported packages. ARR proxy options can affect other sites;
  review their impact instead of applying blanket global changes. Do not stop
  or replace the existing port-80 site.

5. **Create a dedicated PoC HTTPS site and application pool.** Bind the approved hostname and
  certificate to `10.134.64.159:443` with appropriate SNI/host binding and the
  organization's TLS policy. Do not add an HTTP binding for the PoC. Proxy the
  site's root and Streamlit paths to `http://127.0.0.1:8501`, including WebSocket
  upgrade requests, query strings and normal long-lived UI connections.
  Preserve the original Host and establish trusted forwarded HTTPS scheme/host
  information at the proxy; do not trust arbitrary client-supplied forwarding
  headers. Keep response cookies and XSRF tokens intact. Confirm the application's
  external browser origin/port matches the HTTPS address while its listener
  remains loopback-only. CORS/XSRF protections must stay enabled. The current
  launcher has only been validated for localhost; any required external-origin
  configuration must be reviewed and tested before declaring proxy acceptance.

6. **Restrict ingress before publishing the link.** Review effective rules on
  both the NIC and subnet NSGs, Windows Firewall, and any upstream firewall.
  Allow all confirmed `vnet-dig-gld-eastus2` source CIDRs to destination
  `10.134.64.159/32`, TCP 443, with any source port. Scope the rule to this VM's
  HTTPS endpoint, not other destination IPs or services in the VNet. A scoped
  allow rule alone is not a restriction if an existing broader rule
  also permits the traffic. Review Azure's default `AllowVnetInBound` and any
  broader higher-priority rules; place approved destination-specific denies
  for other sources in the correct order where necessary. Windows Firewall
  rules are additive too: inspect existing IIS/GPO allows without disrupting
  unrelated services. Do not use a blanket Windows block rule that overrides
  the intended allowed clients. Keep RDP/management rules unchanged and never
  open ports 8501 or 9999. Preserve existing Azure service egress and IMDS access.

7. **Arrange reliable process startup.** Until a persistent host is approved,
  both existing Python terminals must remain running. IIS does not start or
  supervise these Python processes by proxying to them. For shared availability
  beyond the operator session, choose an approved Windows service wrapper or
  scheduled-task design, with a non-administrator execution account, fixed
  working directory, bounded restart behavior and retained logs. The current
  Python installation and checkout are under the operator's profile; arrange
  an appropriate deployment location and rebuild the venv rather than copying
  it blindly to another account/location. Give the runtime only the required
  source/config read access and state write access; do not grant broad Users
  permissions. Revalidate both components and metrics under that account.

8. **Validate from a client in the allowed VNet address space.** Confirm DNS and certificate
  trust without warnings, HTTP success, and a functioning Streamlit WebSocket
  connection through IIS. Generate one synthetic comparison and test refresh
  and feedback; normal model-usage costs apply. Test a fresh connection from
  an unapproved network to confirm it is denied. Confirm 8501 and 9999 remain
  bound only to 127.0.0.1. Once persistence is implemented, perform an approved
  sign-out/restart/reboot rehearsal. Record the final URL, allowed source ranges,
  owners, and renewal/restart procedure. Before changes, agree rollback that
  removes only the PoC's new binding/rules/site and restores its previous
  settings, preserving existing IIS sites, Azure resources and working localhost
  access.

### Information to return to the PoC operator

- Actual subnet name/resource ID/CIDR, VNet resource group and NIC/subnet NSGs.
- All configured address-space CIDRs for `vnet-dig-gld-eastus2`, any NAT/proxy
  translation and a test client using an allowed VNet source address.
- Approved hostname/private DNS mapping and certificate owner/trust/renewal status.
- Approval and availability of IIS WebSockets, ARR/URL Rewrite, and a Windows
  administrator/change window for the dedicated site and firewall work.
- Owner and approved approach for persistent Python process hosting.

### Temporary exposure and shutdown

Record an owner and review/removal date for whole-VNet access. To withdraw the
shared PoC, stop its dedicated IIS site and application pool, then verify new
HTTPS connections no longer reach the UI. Stop only the PoC's UI/agent processes
as well if all application activity must cease; in-flight Azure model requests
may still complete and incur usage. Preserve unrelated IIS sites and services.

Do not rely solely on deleting the new allow rule: an existing/default NSG or
Windows Firewall allow may still permit traffic. After stopping the PoC site,
review and remove only its newly added bindings/rules, keeping the recorded
restrictions effective until withdrawal is verified. Retain configuration/state
only under the agreed policy. No Azure teardown or deletion of shared resources
is required to disable this viewer endpoint.

These instructions do not turn the trusted-presenter PoC into a production
multi-user application. There is no browser authentication, so every permitted
network client can reach the reduced comparison experience. No extra model or
App Configuration roles are needed just to publish its UI through HTTPS.