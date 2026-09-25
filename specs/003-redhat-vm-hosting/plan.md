# Implementation plan: Red Hat VM hosting

**Historical plan with dated follow-ups.** Later user approvals supersede earlier
implementation-only checkpoints. See the [current evidence](validation.md#history-activation-and-user-acceptance-2026-09-23)
and [documentation tasks](tasks.md#follow-up-documentation-accuracy-and-architecture-2026-09-23).
The current request authorizes documentation changes only, not execution of the
old deployment steps or proposed multi-agent/retrieval designs.

## Technical context

- Existing Python 3.10+ PoCs; prefer an approved Python 3.11/3.12 for the VM.
- Streamlit for both UIs; Uvicorn/A2A for PoC 001 only.
- Keep PoCs independently runnable; a small identical hosting helper is included
  in each, with shared contract tests checking both implementations.
- Host layout: checkout at /opt/elv, one .venv within each PoC, configuration in
  /etc/elv, state under /var/lib/elv-poc001 and /var/lib/elv-poc002.
- Use Bash only for small Linux installation wrappers; retain existing Azure
  PowerShell scripts, which are NOT executed by the hosting installer.
- Azure credentials: explicit ManagedIdentityCredential client IDs in VM mode;
  retain legacy development behavior outside that mode.
- Audit uses LogsQueryClient.query_resource for the configured live/draft stores
  in VM mode. Existing workspace queries remain the non-VM behavior.

## Constitution check

GA Python/Azure interfaces; no new platform framework or service required.
Configuration over custom code: systemd and environment files provide hosting;
the helper exists only to select credentials safely and prevent dotenv override.
Synthetic data and least privilege retained. No production-readiness claim.
The user-provided VM is an explicit exception to preferring managed/serverless
hosting; it is low-volume presenter compute and can be stopped when idle.
No infrastructure changes or secrets are authorized by the installer.

## Work sequence

1. Add deployment/credential contract tests (execute later on VM).
2. Add per-PoC hosting helpers and wire entrypoints, RBAC, OpenAI, Language,
   audit and PoC001 feedback storage to hosted configuration.
3. Add non-mutating readiness checker, two-environment preparation wrapper,
   explicit-apply systemd installer, loopback launcher, three units and nonsecret
   environment examples. Installers do not enable/start services automatically.
4. Add runbook and links/warnings in both READMEs. Add secret/output ignores and
   LF rules for Linux-executed scripts.
5. Inspect diffs, syntax and editor diagnostics without importing/running PoCs.
6. On target VM: install approved dependencies; run tests/pip check and systemd
   verification; validate roles, all demo features, tunnels, health and reboot.

## Deferred infrastructure prerequisites

VM details/access; tenant/subscription/resource inventory; role assignments;
four isolated live/draft stores; compatible model deployment; four initial Search
indexes plus version headroom; Blob/indexer connection; Language; diagnostic logs
and resource-context authorization. Missing prerequisites must not be hidden by
using a single privileged identity or claiming degraded demos are complete.

## Validation

Shared hosting/deployment tests run in each PoC's own VM venv; existing PoC001
tests run from its directory. Use systemd-analyze verify, loopback health checks,
real allowed/denied Azure operations and a reboot rehearsal on the VM. Record
dependency resolutions on that platform; do not invent a tested dependency lock.
Mark remote validation tasks blocked until access is available.

## Effort boundary

Red Hat hosting remains estimated at 2–3 engineering days (allow 4 with minor
compatibility issues), assuming Azure readiness. New-tenant resource preparation
and substantial network remediation are separate from this hosting slice.

## Follow-up: Windows-hosted App Configuration check (2026-09-11)

The customer team has now set up a Windows VM. Its name, approved connection
route and operating-system version are not supplied; the user has no access yet.
The immediate scope is still one-service App Configuration alignment, not a
Windows port of the full Linux/systemd deployment. Keep the Red Hat artifacts
intact; do not claim either VM deployment has been validated.

Add a PowerShell 5.1/7 Windows equivalent of the read-only App Configuration
probe. Use the Azure CLI with an explicit user-assigned managed-identity login,
an ACL-protected temporary CLI cache and restoration of process environment
settings. No user/SPN credential fallback, values/token output, network changes,
identity attachment, role assignment or key writes. Require an explicit operator
acknowledgement that execution is on approved Azure compute. Static parsing is
allowed locally; live execution and identity attachment require the customer's
administrator or later approved VM access. Prefer a narrowly scoped identity;
the existing identity is shared and broadly privileged.

This small wrapper is justified to avoid installing Bash on Windows, preserve
the operator's existing CLI sign-in, and redact raw credential/data diagnostics.
It reuses GA Azure CLI operations and adds no service dependencies.

## Follow-up: Windows comparison milestone (2026-09-16)

The user now has VS Code and this checkout on the Windows Server VM, with local
administrator rights and Python 3.14 available. The confirmed deployment is
GPT-4o. Only one user-assigned managed identity is available; the existing App
Configuration store is empty. The user approved a PoC001-only comparison stage,
with configuration editing/publishing, permission probes, audit and Search
disabled, and localhost viewing until private-IP HTTPS is ready. This is an
explicit reduced milestone, not acceptance of the original full-governance scope.

Use `ELV_DEMO_MODE=comparison` alongside `azure-vm`. PoC001's existing `rbac.py`
owns the one-runtime-identity policy and local disabled-operation errors. Keep
the shared hosting helpers and Red Hat launcher unchanged, preserving the
default five-distinct-identity contract. Guard write/probe/audit operations before
SDK activity, and reject grounded requests before configuration/model access.
Do not disguise application restrictions as Azure-enforced denials.

Use a small Windows foreground launcher with explicit external nonsecret JSON,
protected state, forced loopback listeners and no credential fallback. An explicit
`gpt4o` request profile omits unsupported reasoning controls; the existing asset
request profile remains unchanged. This custom code is necessary because the
systemd launcher is Linux-only and the original full demo cannot safely express
the approved one-identity scope through configuration alone. No new framework,
Azure resource type, identity creation or browser authentication is introduced.

Run focused credential, backend, model-request, Streamlit UI and launcher tests
on the actual VM, then the existing A2A/runtime tests and cross-platform shared
hosting contracts. Confirm dependency compatibility rather than assume Python
3.14 support. Preserve a resolved-version inventory after validation.

The Azure team must separately approve the 12 synthetic baseline/candidate
settings and confirm existing scoped App Configuration/OpenAI access. No original
provisioning/seed/teardown scripts run automatically. A local process-health/UI
check is separate from live comparison acceptance while the store is empty.

Private-IP HTTPS, restricted viewer ranges, an IP-SAN certificate, persistent
Windows process hosting and restart/reboot acceptance are deferred. No network
HTTP relaxation or raw-port exposure was approved. See the
[Windows runbook](../../deployment/windows/README.md) for ordered operation and
the [task record](tasks.md) for remaining gates.

## Follow-up: local live configuration editor (2026-09-17)

The customer deferred shared networking and HTTPS. Retain the administrator
handoff in the Windows runbook as future reference, but do not perform its IIS,
DNS, certificate, firewall or Azure network changes. Users will sign into the
VM through the existing access route and use the local browser.

The user now requests editing the App Configuration experience values from that
local UI. Keep the single managed identity and existing populated production
store. Add `ELV_ENABLE_CONFIG_EDITING` as an explicit runtime JSON opt-in, default
false; do not repurpose the full-governance mode or enable hidden broad writes.
An optional Configuration tab loads one existing baseline/candidate experience
key, then saves it only on an explicit command. The six known keys and two
comparison prompt assets bound the editor's input scope.

Implement an owning configuration-layer update method that rejects other
labels/prefixes, missing keys and unsupported values before writing. Preserve
metadata and use the loaded ETag with `MatchConditions.IfNotModified` so concurrent
edits are not silently overwritten. Use the same explicit runtime credential;
these live updates require Data Owner but do not claim user-specific Azure RBAC
or a draft/publish workflow. Generic writes, audit, Search, permission probes and
persona selection remain disabled. Full-mode/shared hosting behavior is unchanged.

Reuse the comparison cache/context invalidation on save, allowing the next
request to observe the edited profile. Other browser sessions retain their
intentional pinned contexts until refreshed. Add backend/Streamlit/launcher tests
for default-off policy, exact target selection, stale/concurrent/deleted settings,
metadata preservation, failed-save behavior, supported prompt options and fresh
comparison state. Restart the UI to activate the flag, leaving the working agent
alone. Do not change actual Azure values or trigger inference just to deploy the
editor; record live read/UI verification separately from a user-performed save.

## Follow-up: reuse existing Search index (2026-09-18)

The user selected `medical-policies-vector` and approved all its documents for
retrieval and sending bounded excerpts to the existing Azure OpenAI deployment.
The index schema GET returned 403; no role escalation was attempted. The user
provided its field names, and zero-document queries verified the chosen text,
metadata and filter fields. Existing CMK/network access issues were not reopened.

Keep networking local and use the same explicit managed identity. Add an
operator-controlled `ELV_ENABLE_RAG` opt-in, HTTPS Search endpoint and exact
`ELV_SEARCH_ALLOWED_INDEXES`; defaults remain off and inherited settings cannot
broaden access. Only `knowledge:*` reads under baseline/candidate are newly
enabled; draft reads, persona switching, publishing and audit remain disabled.

Generalize the existing query/normalization code with configurable field names,
optional empty metadata mappings, search fields and explicit filters. Preserve
legacy sample defaults. For the selected schema, use Content/Title, Status/State,
PublishDate and BlobName. This first integration is simple keyword RAG; it does
not use ContentVector, create embeddings, modify an index or run an indexer.
No source text means no model request; unsupported modes and unapproved indexes
fail rather than dropping filters or silently returning ungrounded responses.

Reuse the version-checked configuration editor for validated knowledge settings,
and add a grounding toggle plus source citations to the comparison UI. Contexts
pin knowledge settings until refresh; switching grounding or saving configuration
clears the current session's contexts. Extend the existing initializer with an
explicit knowledge-only JSON input, preview by default, atomic create-only
writes, preserved experience settings and readback. The user approved the exact
32 proposed knowledge entries and one live two-response test after preview.

This scoped custom code reuses the existing Search SDK, A2A runtime, prompt assets,
editor and initializer because the original fixed sample schema does not match
the existing index. It introduces no new service, authentication mechanism or
provisioning dependency. Retain the runtime index allowlist and actual Azure
permissions as distinct from editable content-selection filters; neither a
configuration label nor a document status value is per-user authorization.

Validation includes field mapping/filter preservation, default-off and index
restrictions, no-source behavior, editor version checks, UI toggle/citations,
knowledge-only initialization, existing PoC/shared-hosting regressions and the
approved live RAG comparison. Document observed metadata values, supported modes
and remaining quality/vector/document-authorization limitations separately.

## Follow-up: reconcile healthcare branch on the VM (2026-09-22)

Repair merge `d706a82` while retaining the Windows VM deployment and the other
branch's healthcare prompts and Search configuration improvements. Existing
Azure resources, identity, data, field mappings and runtime JSON are authoritative.
No resource migration, roles, seeding, service restart or live inference is part
of this source repair; the user will test locally after deployment.

Restore configuration imports/conflict handling and comparison mutation guards
without discarding full-mode mutation outcomes or best-effort history. Normalize
core Search controls while preserving explicit blank filters and VM field mappings.
Restore the healthcare runtime tests alongside VM tests: full previews retain
disabled/unavailable behavior, while VM grounding keeps opt-in, allowed-index
and no-model-on-empty protections. Retain healthcare privacy/provenance rules
and the same claims-and-appeals question in both UI response modes.

Reuse the six-control Search form in the VM Configuration tab with approved-index
options and keyword-only mode. Save to the existing live store with complete
validation, loaded ETags, unchanged-value skips and partial-write reporting.
Keep the individual mapping editor, full-mode draft editor and history code.
Do not enable Blob history or additional identities on this VM implicitly.

Validate real source through offline backend, prompts, runtime, forms, Streamlit
and shared deployment tests. Stage the incoming Blob SDK in a temporary test
folder to avoid modifying running dependencies. The user must stop both processes,
install matching requirements into the PoC venv, then restart via the Windows
launcher. The grouped-save adapter reuses existing contracts because the full
demo's draft writer is deliberately unavailable in comparison mode; no new
framework or Azure service is required.

## Follow-up: filter diagnostics and citation visibility (2026-09-22)

The user reported an A2A failure after editing a filter. Existing agent logs
showed Search HTTP 400 for `industry`, then lowercase `status`, neither matching
the configured existing index. Preserve the filter and selected index; surface
a sanitized query rejection through the existing A2A validation path and
distinguish a failed task from a transport outage. Remove the incompatible
sample filter hint from the VM form without changing the full-demo defaults.

The user then supplied a completed grounded task and configuration screenshots
showing an inline setting but no markers in the answer. Inspect the existing
task by local A2A GET with `A2A-Version: 1.0`; do not repeat model requests merely
to reproduce it. Add pinned citation style and check status to safe A2A provenance
and identify the source table as retrieved material, not proof of citations.

Retain healthcare grounding instructions. Check nonempty inline-mode output for
numeric source markers and valid source numbers. Withhold missing/invalidly cited
model text, without assigning unsupported citations or automatic inference
retries. The check does not establish sentence-level support, factual accuracy
or source relevance; document that limit. None/footnote and empty-model handling
remain separate. Validate with offline runtime, protocol and UI tests, then
restart only the known local PoC processes; no cloud configuration/index writes.

## Follow-up: VM configuration history in Blob Storage (2026-09-22)

The user asked to enable storage-backed configuration history in the current
single-identity VM workflow. They approved the existing storage account and
dedicated `poc001-config-history` container, reported that the container still
needs creating, explicitly permitted reuse of the runtime identity for history
writes/reads, and chose implementation/offline checks only. No live Storage test,
container creation, permission change or configuration mutation is authorized
for this implementation step.

Reuse change_history.py, its create-only JSON writes, bounded reads and safe CSV
export. Add an explicit default-off `ELV_ENABLE_CONFIG_HISTORY` in runtime JSON,
validate the Blob target locally, and clear inherited settings to prevent implicit
activation. Comparison-mode reader/writer use the validated runtime identity
only when enabled; full-governance separate identities and disabled Log Analytics
access in comparison mode remain unchanged.

Record the actual live write helper's known before/after values, ETags and result.
Preserve configuration errors and unknown timeout outcomes; never retry/rollback
configuration because history failed. Skip no-ops. Grouped saves share an operation
ID and aggregate history warnings without masking partial config writes. Expand
the history allowlist for VM field mappings without widening the full-demo editor.
Reuse the existing history view in a separately gated Change history tab, with no
reads on entry, and show history warnings for single-key saves across reruns.

Stage the approved account/container with the flag false until administrator
preparation. Document private container creation, container-scoped permissions,
shared-identity limitations, activation and user-performed acceptance. Tests use
mocked clients/transport only and cover opt-in, original values, races, failures,
no-op behavior, grouping and warning/read UX. No new framework, Azure account,
logging platform or credential mechanism is introduced.

## Follow-up: explicit history-container setup script (2026-09-22)

The user requested a script to create the dedicated private container and set
the existing local history configuration accordingly. Retain the earlier
implementation-only boundary: author/test the script and run its local preview,
but do not apply it against Azure or create an event on the user's behalf.

Reuse Windows runtime validation and the installed Blob/Identity SDKs. Default
to a no-network, no-file-change preview. Explicit `--apply --approved-azure-host`
selects the existing VM identity, gets only the named container's properties,
creates it privately if absent, and confirms privacy before enabling the local
flag. A racing create is rechecked. Existing public containers are rejected,
not converted. There is no account provisioning, role assignment, key/SAS path,
Blob content operation, service restart or configuration-store mutation.

Replace only the local history flag semantically, preserving other parsed JSON
values and the destination Windows DACL. Detect runtime-file edits made during
setup; document the need to pause other writers because this is not a distributed
transaction or file compare-and-swap. A container can remain if later steps fail;
do not delete it or overwrite configuration to manufacture rollback. Tests must
cover preview, approval, creation/reuse/races/privacy, permission failures,
idempotence and local preservation, with Storage mocked throughout.

## Follow-up: documentation accuracy and architecture (2026-09-23)

Implement the approved documentation plan in the existing whitepaper, reference
standard, PoC READMEs, Windows/Storage runbooks and this feature's evidence/task
record. Correct current identity, editing, Blob-history activation, refresh and
retrieval claims before adding explicitly proposed compound-request coordination
and large-corpus metadata guidance. Use read-only healthcare examples, cover both
shared and caller-specific corpus access, and start with metadata assessment.

Preserve the standard's security, identity, IaC and observability requirements;
record VM exceptions and unresolved owners rather than claiming conformance.
Keep new diagrams as Mermaid in Markdown, distinguish code-present PoC002 from
live acceptance, and label user-confirmed history evidence. Validate document
links, diagram syntax/rendering and scope. Do not change code, prompt assets,
runtime JSON, services, Azure resources, permissions or Search indexes.