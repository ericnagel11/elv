# Config-Driven Healthcare Responses PoC

A trusted-presenter demonstration of configurable member-support wording,
claims-and-appeals retrieval, draft approval and application change history.
It maps to Scenario 1 in the
[PoC Scenario Catalog](../../specs/001-poc-scenario-catalog/spec.md).

Use the **same exact question in grounded and ungrounded modes**:

> I received a denial notice for my health insurance claim. How can I appeal it?

Baseline and candidate retain different tone, detail, reading level and structure;
both are Contoso Health Plan administrative member support, not different
industries. Use synthetic content only: no PHI, member IDs, claim numbers,
diagnoses, tokens or secrets in messages, configuration or exported evidence.

**Implemented:** the Blob history contract is in
[change_history.py](change_history.py), the six-key Search contract in
[search_settings.py](search_settings.py), and the grounding gate in
[experience_runtime.py](experience_runtime.py), integrated through
[config.py](config.py) and [app.py](app.py). Deploy the complete matching change,
dependencies and configuration before accepting the full workflow below. A
legacy LA-only Audit tab or retail-prefilled question indicates an older
deployment, **not** a reason to provision Log Analytics. Target Azure acceptance
remains required; local mocked tests do not establish live Blob permissions.

**Current VM deployment:** follow the
[Windows runbook](../../deployment/windows/README.md), not the development or
full-governance setup below. It keeps the existing single managed identity,
App Configuration/OpenAI/Search resources, external runtime JSON and localhost
listeners. Healthcare prompts and the grouped RAG form work in that mode too;
separate draft identities are not enabled. Optional VM Blob history is implemented
behind an explicit opt-in, currently disabled until its private container exists.

## What changes without a code release

- `experience:*` configures persona, tone, verbosity, reading level, response
  structure and the selected versioned prompt asset.
- `knowledge:*` selects an existing index/alias, OData scope, result count,
  query mode, citations and whether retrieval is enabled.
- An experience designer edits the draft `candidate`; an approver publishes to
  the production `candidate`. Both prefixes use the same App Configuration RBAC
  boundary. Labels alone do not provide separate store-level authorization.
- Configuration changes take effect in fresh runtime contexts after refresh.
  **New application code, prompt bodies, dependencies and environment settings
  still require deployment/restart.** Existing stored settings are not migrated
  just by updating repository defaults or examples.

## Runtime and A2A contexts

Streamlit calls a separate response agent through **A2A 1.0**. The first task in
an A2A `contextId` resolves and pins the production profile and knowledge scope.
Later tasks in that context keep those values; external clients' existing
contexts do not change when a draft is published. Start a new context to observe
newly published configuration.

The comparison extension accepts `baseline`/`candidate` and grounding intent,
not arbitrary prompt assets, stores, labels, filters or credentials. The runtime
requires **both** a grounding request and published `knowledge:enabled=true`.
A caller cannot override disabled server configuration. In the full demo, a
disabled scope uses the experience prompt and makes **zero Search calls**, including direct
`run_grounded()` previews. It can still call OpenAI; disabled retrieval does not
mean offline generation. Missing references must not be reported as successful
grounding.

The VM comparison is stricter: an explicitly grounded request with disabled or
unconfigured Search is rejected; empty retrieval returns a no-sources result
without inference. Turning off the grounding toggle still permits ungrounded
healthcare guidance. Both modes retain the same member-support question.

Publishing (including partial failure) automatically clears the active UI A2A
context IDs, cached profiles/scopes and displayed results. Regenerate to resolve
production again. **Refresh configuration from Azure** does the same for external
configuration changes; draft saves invalidate knowledge previews. Do not treat a pinned old conversation as a failed
save, or promise that all remote contexts refresh automatically.


### Windows VM / one-identity comparison

Use the [Windows comparison runbook](../../deployment/windows/README.md) for the
current Windows VM and existing GPT-4o deployment. It launches the UI and A2A
agent on localhost with one explicit managed identity, external nonsecret JSON
settings and no client-secret/developer fallback. The App Configuration store
must contain both synthetic comparison profiles before responses can be generated.

This mode disables persona switching, publishing, permission probes and the full
governance audit workflow.
Search is off unless `ELV_ENABLE_RAG` is explicitly enabled with an approved
endpoint/index allowlist. Configuration writes remain off unless the Windows runtime JSON explicitly
sets `ELV_ENABLE_CONFIG_EDITING` to `"true"`. That option adds a **Configuration**
tab for existing baseline/candidate experience values, using direct live updates
with ETag conflict checks under the same managed identity. It does not simulate
separate Azure roles or a draft approval workflow. Full governance remains the
default outside comparison mode.

The grouped **Search configuration** form is available under **Configuration >
Knowledge**. Load current settings, edit the six controls, and explicitly save.
Approved-index and keyword-only restrictions remain, blank filters need
acknowledgment, and field mappings can still be edited individually. Version
checks and partial-result reporting prevent misleading claims of atomic saves.
Existing Azure settings are not migrated by new industry defaults.

Optional [VM configuration history](../../deployment/windows/README.md#configuration-change-history-in-blob-storage)
uses `ELV_ENABLE_CONFIG_HISTORY` and a dedicated private Blob container. The user
approved reusing the runtime managed identity for this limited mode's writes and
reads; the full demo's distinct-identity policy below remains unchanged. History
is best-effort configuration before/after evidence, not prompts/responses or
per-user attribution. Storage failures remain separate from the save outcome.
The target is staged but disabled until administrator preparation and a user-run
live test are complete; the app never creates the container or grants roles.

Optional [existing-index RAG](../../deployment/windows/README.md#ground-responses-with-an-existing-search-index)
maps `Content`, `Title`, `Status`, `State` and source metadata through
`knowledge:*` settings. The first integration uses keyword retrieval from the
approved `medical-policies-vector` index, not its vectors. Enable **Ground with
AI Search** for sourced responses; edit the per-profile OData filter through
**Configuration > Knowledge**. Azure resource tags do not become document
filters automatically. This integration does not recreate or modify indexes.

Users currently sign into the VM and view the PoC at localhost. Shared networking
and HTTPS are deferred by the customer; the Windows runbook retains the proposed
administrator steps for future use. Persistent Windows services are not installed.

### Red Hat VM / existing Azure services

The following draft, persona and history setup applies to the separate full
governance demo, not the active Windows single-identity comparison.

### Runtime boundaries

| Layer | Responsibility |
| --- | --- |
| Streamlit governance UI | Presents comparisons, edits draft configuration, publishes as the acting persona and displays history |
| A2A response agent | Pins production configuration per conversation; keeps Search filters, prompt rendering and model calls behind the runtime boundary |
| Azure App Configuration | Stores experience and knowledge settings; distinct live/draft stores enforce the change boundary |
| Azure AI Search | Retrieves approved-scope reference excerpts; does not generate the answer |
| Versioned Prompty assets / Azure OpenAI | Render healthcare instructions and generate replies with or without retrieved context |
| Dedicated Blob history | Records app-observed setting changes after writes; separate from source documents and Search indexer storage |

### Required services and tools

- Approved Python 3.10+ environment with the matching
  [requirements.txt](requirements.txt) dependencies, including the Blob SDK.
- Distinct existing live/draft App Configuration stores, approved OpenAI endpoint
  and deployment, and an existing Search index/alias compatible with this app.
- Approved synthetic healthcare references and filterable healthcare/approval
  metadata. Keep the customer's index selection and data unchanged by default.
- For Blob history: the private dedicated container and separate identities
  described below. **No Log Analytics workspace is required for PoC001 Blob mode.**
- The host's approved routing, DNS, certificate/proxy policy and identity grants.
  Successful access to one Azure service proves nothing about another.

**Do not run legacy provisioning or teardown against customer/shared services.**
[scripts/setup.ps1](scripts/setup.ps1),
[scripts/setup-governance.ps1](scripts/setup-governance.ps1),
[scripts/setup-knowledge.ps1](scripts/setup-knowledge.ps1) and
[scripts/teardown.ps1](scripts/teardown.ps1) are disposable-environment
provisioners/destructors, not reuse-only helpers. In particular, the legacy
governance script provisions Log Analytics and identities; it is not needed for
the Blob history path. The knowledge provisioner can create/modify services,
permissions, blobs and Search definitions even when names are supplied.
No resource, index, role, diagnostics, retention or public-access change happens
automatically through the application or these environment examples.

### Hosting and identity modes

For Linux systemd deployment, use the
[Red Hat runbook](../../deployment/redhat/README.md) and
[deployment environment example](../../deployment/redhat/poc001.env.example).
[../../deployment/redhat/run.py](../../deployment/redhat/run.py) explicitly rejects
Windows; it is not a Windows service launcher.

`ELV_HOSTING_MODE=azure-vm` uses explicit VM-attached managed identities and ignores
dotenv and local persona-secret files. Supply process/service environment values
for both the UI and agent. In the full demo, persona and audit-reader UUIDs must
remain complete, nonzero and distinct; the extra history writer is checked lazily
inside the best-effort history boundary. The VM and all presenters are one trust
boundary, not per-person or per-process identity isolation.

Development mode loads the project-local dotenv without overriding existing
process values. Copy [.env.example](.env.example) to the local dotenv only for
this mode and fill in approved existing metadata; never copy credentials from
another host. `DefaultAzureCredential` uses the approved developer authentication
workflow when persona credentials are absent. Blob writer and reader also use
the developer credential in this mode: merely filling the VM UUID fields does
not demonstrate separate identity permissions. The legacy persona-secret
shortcut is not production authentication.

### Run on Windows (development)

In two PowerShell terminals opened in this PoC folder, use an **already prepared,
approved** environment and authentication workflow. Do not bypass signing policy
or run setup scripts to resolve customer resource gaps. Start the runtime in the
first terminal and the UI in the second:

```powershell
# Terminal 1
.\.venv\Scripts\python.exe a2a_server.py

# Terminal 2
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501
```

Open `http://127.0.0.1:8501`. The local agent defaults to
`http://127.0.0.1:9999` and publishes `/.well-known/agent-card.json`.
These trusted local demo listeners are not authenticated public endpoints.
Do not expose them by opening firewall/NSG rules; production requires an approved
HTTPS/authentication design. Restart **both** processes after environment or
dependency changes. On an approved Windows Azure VM, use the approved process
environment with `azure-vm` credentials instead of developer dotenv/sign-in;
the Linux launcher/systemd package still does not apply.

## Default Blob application history

| Setting | PoC001 deployment value |
|---|---|
| `ELV_AUDIT_BACKEND` | `blob` (also the default when unset) |
| `ELV_AUDIT_BLOB_ACCOUNT_URL` | `https://tenxengbenefitaistandard.blob.core.windows.net` |
| `ELV_AUDIT_BLOB_CONTAINER` | `poc001-config-history` |
| `ELV_AUDIT_BLOB_WRITER_CLIENT_ID` | Separate approved VM-attached UAMI **client UUID**, distinct from every persona and the audit reader |
| `ELV_MI_AUDIT_CLIENT_ID` | Reused dedicated audit reader **client UUID** |

The owner must precreate/reuse this **dedicated private container** and approve
the network path. Grant the writer **Storage Blob Data Contributor** and the
reader **Storage Blob Data Reader**, each at **only this container**, not account,
subscription or root scope. Do not grant runtime/designer/viewer personas history
write rights. A prefix is not an RBAC boundary. The application never creates
or overwrites the container or changes cloud permissions. It uses the standard
HTTPS Blob hostname with no embedded credentials, SAS, query or container path.
See [storage guidance](../../deployment/storage/README.md#poc001-application-change-history).

### What the history means

- **Application-only before/after history** for the allowlisted experience and
  knowledge settings, with key, label, store, UTC time, old/new values and etags
  when known, outcome and an operation ID for grouped saves/publications.
  Unknown prior values are distinct from known absent or empty values.
- Persona and configured client UUID identify the acting service credential,
  **not an authenticated human**. App-observed failures and permission probes
  are not a feed of every Azure denial. Same-value permission probes are not
  business changes; ordinary unchanged saves should not appear as new changes.
- **No coverage of direct Portal/CLI edits, seed/provisioning scripts or other
  external writers; no historical backfill.** History is not a reconstruction
  of all App Configuration activity.
- No questions, retrieved documents, generated prompts, credential tokens or
  arbitrary exception bodies in the history payload. Configuration values are
  recorded: operators must not enter PHI, secrets or personal data in those keys.
  This is not an automatic sensitive-data detector.

Recording is **best effort**: a missing/invalid account, container or writer UUID,
storage denial or timeout yields a visible warning while an otherwise permitted
App Configuration operation proceeds. A failed configuration write remains a
failure. History failure must not cause the app to retry the configuration write
or block generation. Normal persona validation, Azure authorization and conflict
validation are not bypassed. Read outages must say **unavailable**, not "no
events"; an empty selection is not evidence that no changes ever happened.

Each event attempts a unique JSON block blob with `overwrite=False`, not a shared
CSV append. This is **not immutable, tamper-proof or WORM storage**: Contributor
can overwrite/delete, and a crash between configuration write and history upload
can leave a gap. There is no cross-store/Blob transaction, automatic rollback,
local outbox or fallback to Log Analytics. Retention/lifecycle remains the
resource owner's policy, never an application change.

### Review and CSV acceptance

In **Audit trail**, select the history window (initially 24 hours), select
**Refresh change history**, apply store/persona/outcome filters, and use
**Download visible history as CSV**.
The helper accepts an interval of at most 30 days and returns at most 500 events,
newest first among scanned rows. Listing/download/byte/time budgets and malformed
files can make the selection partial: heed the warning; it need not contain the
newest events from the entire requested interval.

CSV is generated from exactly the selected visible rows, not a new cloud query.
It has stable columns, quoting for commas/newlines and spreadsheet-formula
neutralization. Protect downloads as configuration evidence; CSV is not a backup
or completeness guarantee. Verify this UI integration after deploying the
matching application changes; do not infer it from a successful Blob list probe.

### Optional legacy Log Analytics

Only `ELV_AUDIT_BACKEND=loganalytics` opts PoC001 into the legacy resource-log path.
It requires an existing workspace customer UUID in
`AZURE_LOG_ANALYTICS_WORKSPACE_ID` and approved `AACAudit`/`AACHttpRequest`
diagnostics/ingestion. VM mode additionally requires distinct live/draft ARM IDs
in `AZURE_APPCONFIG_RESOURCE_ID` and `AZURE_APPCONFIG_DRAFT_RESOURCE_ID`, with
resource-context query rights for the dedicated audit reader. Do not add broad
workspace access to suppress a denial. Non-VM legacy queries use the developer
credential and configured workspace.

The Linux launcher validates workspace UUID and audit ARM IDs **only** for this
explicit PoC001 mode or for PoC002. Blob URL/container/writer settings are not a
startup gate. PoC002 remains legacy LA-required **regardless** of
`ELV_AUDIT_BACKEND`; this feature does not change its identities or application.
Legacy resource logs are not the same before/after/CSV application-history feed.

## Seed and migrate existing configuration

[scripts/seed-config.ps1](scripts/seed-config.ps1) targets **existing** stores
using an existing CLI sign-in (`-AuthMode login` by default). It does not sign in,
provision, import/export a backup, change indexes/permissions or delete keys.
It checks native CLI failures and hides values/CLI error bodies in its output.
Its scope and behavior are:

| Option | Actual behavior |
|---|---|
| Default | **Add missing keys only**; preserve all existing values, including retail/custom personas and filters. Production gets `baseline` and `candidate`; an optional distinct draft store gets only `candidate`. |
| `-WhatIf` | Resolve the scoped plan with Azure reads and inspect CLI help when writes would be planned, but perform no writes. It is not an offline preview; values are hidden. |
| `-OverwriteExisting` | Explicitly allow selected existing seed values to be replaced. Review a matching `-WhatIf` first and take any required protected backup separately; there is no automatic backup or unconditional confirmation prompt. Use `-Confirm` when per-operation confirmation is wanted. |
| `-Keys` | Exact fully-qualified names from the twelve known `experience:*`/`knowledge:*` seed keys, not wildcard patterns. Omission selects all seed keys not otherwise skipped. |
| `-Labels` | `baseline` and/or `candidate`; defaults to both. `candidate` affects production **and** the supplied draft store, not draft only. |
| `-KnowledgeIndex` | Value for missing `knowledge:index` (default `kb-current`). Existing index selection is preserved even with overwrite unless this parameter is **explicitly supplied** and the key is selected. Index-name validation is lexical, not proof of existence/schema/access. |
| `-SkipKnowledge` | Omit every knowledge key, even one selected by `-Keys`. It does not disable existing retrieval or delete settings. |

Newly seeded profiles use healthcare member-support personas and the same
approved-only filter in **both** production and draft:
`industry eq 'healthcare' and status eq 'approved'`.
Seeds enable knowledge (`true`); missing runtime configuration safely defaults
to disabled (`false`). Seeding missing keys does **not** migrate existing retail
values. Review the actual values securely before opting into a scoped overwrite.

Preview only, from this folder with approved store names substituted:

```powershell
# Add-missing plan; preserves existing values.
& .\scripts\seed-config.ps1 -AppConfigName '<live-store>' -DraftAppConfigName '<draft-store>' -WhatIf

# Review only the proposed healthcare persona/filter migration for candidate.
# This selects candidate in BOTH supplied stores.
& .\scripts\seed-config.ps1 -AppConfigName '<live-store>' -DraftAppConfigName '<draft-store>' -Keys experience:persona,knowledge:filter -Labels candidate -OverwriteExisting -WhatIf
```

Applying without `-WhatIf` makes real writes and requires separate owner approval.
The script plans first, rejects selected locked overwrites, then rechecks each
key's presence/ETag/lock before writing. If installed CLI help exposes both
`--if-match` and `--if-none-match`, it uses conditional writes. Otherwise it warns
that the recheck is **not atomic**: pause concurrent writers; a race remains
between read and write, including CLI retries. Writes stop on the first failure;
earlier successful keys remain and are not rolled back. Seed activity is outside
application-recorded history. Do not bulk reseed or replace a customer-selected
index merely to match repository defaults.

## Healthcare Search controls

The dedicated Search editor is under **Governance and RBAC > Search configuration**, separate
from experience wording, in the full demo. On the VM use **Configuration >
Knowledge > Search configuration** with its deployment restrictions. The six
shared keys and their full-demo contract are:

| Key | Control / values | Missing-setting default |
|---|---|---|
| `knowledge:enabled` | Toggle; persisted `true`/`false` | `false` (seed uses `true`) |
| `knowledge:index` | Existing approved index/alias text; lexical validation only | `kb-current` |
| `knowledge:filter` | OData text; preserve expression apart from outer whitespace | `industry eq 'healthcare' and status eq 'approved'` |
| `knowledge:top_k` | Integer **1..20** | `3` |
| `knowledge:query_mode` | `simple` or `semantic` | `simple` |
| `knowledge:citation_style` | `inline`, `footnote` or `none` | `inline` |

An **explicit blank filter means no filter**, not the approved-only default;
review/acknowledge the wider scope before saving. Absent/None values use defaults.
Local validation is not a full OData parser and cannot prove schema compatibility,
authorization or source approval. Never silently rewrite invalid existing enum
or numeric settings simply by opening the editor. Deployment acceptance should
verify all six controls, stored-versus-fallback visibility, validation before
writes and read-only/default visibility when draft access is unavailable.

[knowledge.py](knowledge.py) defaults to `title`, `content`, `url`, `industry`,
`audience`, `status` and `effective_date` for the sample index. Existing-index
mappings override these names and can omit optional fields. The target must
support its mapped fields and filter; an explicit blank filter stays blank.
Semantic mode requires an appropriate tier and
the existing `kb-semantic` configuration; reported keyword fallback is not proof
of semantic operation. No vector/embedding query is sent by this code. A `top=0`
connectivity probe or an index name containing "vector" does not prove this
schema contract. Do not rebuild customer indexes or upload samples automatically.

## Try the healthcare demo

After the deployment gates pass:

1. Use the exact question above in **Experience comparison**. With **Use
   configured Search grounding** selected, both variants request grounding but
   still honor their published enabled flags. Turn it off to compare ungrounded
   healthcare responses, not a retail scenario.
2. As **Experience designer**, edit a candidate draft setting, for example
   `experience:verbosity` or `knowledge:top_k` within 1..20. Inspect the diff;
   this does not change production yet. Keep the approved-healthcare filter.
3. As **Release approver**, publish and review the actual completed/failed keys
   and history warnings. Publication is not an atomic transaction or automatic
   rollback. Refresh configuration and regenerate in new A2A contexts.
4. On **Knowledge scope**, compare live and draft using the same question.
   Both default to approved healthcare content. Compare the actual settings and
   observed sources: more than the filter can differ, and matching scopes may
   retrieve the same documents. There is **no seeded draft healthcare document**
   to promise or fabricate. Do not broaden scope just to force a different answer.
5. Set the draft `knowledge:enabled=false` for an approved preview. Confirm a
   disabled note, no retrieved sources and no Search call. After approved
   publication and refresh, production should honor the same gate.
6. Review app-recorded before/after changes and grouped publication outcomes in
   **Audit trail**, then export the visible selection as CSV. Feedback preferences
   are separate local A/B evidence, not the configuration history.

Ungrounded assets [prompts/response.v1.prompty](prompts/response.v1.prompty) and
[prompts/response.v2.prompty](prompts/response.v2.prompty) give general process
guidance and direct the member to their denial notice/member services; they must
not invent deadlines, eligibility, coverage decisions or appeal outcomes. The
grounded [prompts/response.v3.prompty](prompts/response.v3.prompty) uses only
retrieved references, with the selected citations, and acknowledges missing
answers. All modes prohibit clinical advice and requests for PHI. Repository
healthcare documents are synthetic references, not real coverage/medical advice;
prompt sample metadata is not automatically applied as runtime configuration.

With retrieved references but insufficient evidence, v3 returns the exact
`NO_SUPPORTED_ANSWER` marker. The runtime replaces it with a safe member-facing
message and reports `insufficient_evidence`, not a citation-format failure.
Additional text cannot use that marker to bypass inline citation validation.
Substantive inline answers without valid numbered markers remain withheld;
valid marker numbers do not prove factual support or source relevance. There is
no automatic model retry and no fabricated citation. Existing task results are
not rewritten by a prompt update.

The default appeals question requires references that actually describe an
appeals process. Retrieving medical-policy documents alone does not establish
that the existing index contains that information. Review source relevance and
the approved knowledge scope; do not weaken citations or remove filters just to
force an answer.

### RBAC and permission checks

Select **Acting as** and use **Governance and RBAC**:

| Acting as | Edit draft | Publish to production |
|---|---|---|
| Viewer / Auditor | Azure denial | Azure denial |
| Experience designer | Allowed | Azure denial |
| Release approver | Allowed | Allowed |
| Application runtime | Denied; cannot read draft | Denied |

These outcomes require actual approved Azure assignments, not UI-side role
simulation. Authentication failure is distinct from Azure 403. **Run permission
check** performs real calls; its write probes rewrite an existing value unchanged
and must be labeled `permission_probe`, not ordinary business edits. Use only
approved demo stores. The selected persona is not end-user authentication; the
dedicated history reader is independent of the currently selected persona.

## Acceptance evidence and limits

### Offline checks

From the PoC folder in a prepared Python environment:

```powershell
python -m unittest discover -s tests -v
& .\scripts\tests\test-seed-config.ps1
```

The suites include real Streamlit AppTest interactions, SDK models with mocked
transports, configuration conflict/partial-publish cases, audit outages, CSV
escaping and healthcare prompt rendering. They do not authenticate to Azure or
call the model. The seed suite uses a local function-mocked CLI; it does not
establish native Azure CLI quoting or live service behavior. Do not run
[_diag.py](_diag.py) as an offline test: it performs live Search/model requests.

Local verification on 2026-09-21 used Python 3.12 on Windows: 140 PoC tests,
22 deployment/hosting tests and the PowerShell seed suite passed. This does not
establish Python 3.14 compatibility or actual customer-VM acceptance.

### Customer-VM acceptance

Capture the exact healthcare question in both modes, six Search settings with
draft/live differences, enabled/disabled retrieval evidence, new context behavior,
real RBAC results and before/after history with filtered CSV. Test missing/denied
history using mocks first; never revoke shared customer permissions to force a
failure. Confirm reader can read but not upload at the dedicated container.

Offline tests and editor diagnostics are not Azure/network acceptance. The
[deployment tests](../../deployment/redhat/tests/test_deployment.py) cover
backend-aware startup without cloud calls; they do not execute application
history/CSV or certify UI integration. Validate the matching application tests
and owner-approved end-to-end workflow separately.

This PoC provides no immutable compliance audit, human identity verification,
historical backfill, automatic rollback/delete workflow or external-edit polling.
Resource owners manage retention, costs, permissions and cleanup. Do not run
teardown or delete shared resources when the demonstration ends.

### Cost and production boundaries

OpenAI calls incur token charges. Search/App Configuration retain their existing
tier/capacity charges; Blob history adds small per-event writes, storage and
bounded read/download transactions. Listing a long history window costs more
than a short one. This change adds no Log Analytics workspace or always-running
audit worker. Retention, soft delete or immutability policies require separate
owner review; the app never installs or changes them.

For production, add authenticated user attribution, a durable transactional
change/outbox design, appropriate record retention and immutable storage if
required, and independent operational monitoring. The presenter-only identity
selector and warning-only audit failures are explicit PoC limitations.
