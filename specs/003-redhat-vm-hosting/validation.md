# Validation record — 2026-09-08

## Supplied VM inventory (not inspected inside the VM)

The operator supplied Azure portal metadata on 2026-09-08:

- Running Linux VM; Red Hat Enterprise Linux 8.10.
- East US 2; Standard D2lds v5, 2 vCPU and 4 GiB RAM.
- Private subnet; no primary NIC public IP or public DNS name shown.
- Subscription and resource-group identifiers were supplied in the conversation;
  organization-specific identifiers are intentionally not duplicated here.

RHEL 8.10 is within the planned RHEL support range. The 4 GiB VM is a reasonable
candidate for initial low-concurrency testing, not verified capacity for both
PoCs. The earlier 8 GiB suggestion was a planning allowance, not a minimum.
Measure available memory, installation peaks and concurrent demo usage before
requesting a resize. No GPU or Windows desktop is indicated by this inventory.

A private subnet alone does not establish a usable connection route. VM name,
private address/approved SSH alias or Bastion route, login/install permissions,
installed Python, package egress and dedicated/trusted workload status remain
unknown. The supplied subscription ID is not the tenant ID. Tenant placement,
managed identities and target-service access still need verification. No public
IP or public application-port exposure is required by the deployment design.

## Completed source checks

- Git diff whitespace check passed.
- Both new Bash wrappers passed bash -n (syntax parsing only).
- Linux shell files contain LF, not CRLF.
- Both standalone hosting helpers are byte-identical.
- File targets in the deployment runbook and modified PoC READMEs exist.
- Editor diagnostics reported no errors in changed PoC/deployment/spec folders.
- Static review confirmed no Azure provisioning/teardown commands are invoked
  by the hosting scripts and no automatic service enable/start during install.
- Fifteen remote-executable test methods were authored, covering both PoCs'
  hosting helpers and deployment contracts. They have **not** been executed.
- No implementation extension hooks were configured.

## Not performed / blocked

- No PoC, Python test or application dependency installation was run locally.
- A usable local Python parser was unavailable; no AST/compile validation is
  claimed. Editor diagnostics are not a substitute for Python execution/tests.
- RHEL VM readiness, dependency resolution, PowerShell 7 execution, systemd
  verification, listener/health checks, RBAC, diagnostics, full demos and reboot
  recovery require the target VM and remain unverified.
- No Azure credentials were collected; no tenant resources, identities,
  assignments, content or configuration were changed.

## Handoff prerequisites

Provide the VM name and approved SSH/Bastion connection route (not private keys
or passwords), installation permissions, trusted VM and tenant confirmation,
and the nonsecret existing-resource/managed-identity mapping. RHEL version and
size have been supplied above; installed Python and host readiness can be
inspected after approved access is available.
Runtime configuration uses administrator-managed files outside the checkout.
Azure resource preparation/seeding is a separate approved operation.

Use [the deployment runbook](../../deployment/redhat/README.md) to execute the
remaining checks on the VM. Keep T009–T012 in [tasks.md](tasks.md) open until
their actual evidence is available. Source support is implemented; deployment
and full new-tenant migration are not complete.

## Windows comparison milestone — 2026-09-16

This later evidence concerns the user-approved **PoC001 comparison-only** scope
on the Windows VM. It does not establish the original Red Hat deployment,
PoC002, multi-persona governance, audit or private shared HTTPS acceptance.

### Inspected host and dependencies

- Windows Server 2025 Datacenter, version 10.0.26100, 64-bit.
- Python 3.14.7 with OpenSSL 3.5.7; Windows PowerShell 5.1.26100.33296.
- PoC001 dependencies installed in its own `.venv`; `pip check` passed.
- NLTK `cmudict` installed for the UI account; a synthetic `textstat` reading-ease
  calculation completed successfully.
- The resolved package inventory is retained locally in the ignored
  `pocs/001-config-driven-responses/.installed-requirements.txt`. It is evidence
  of this installation, not a pre-existing or hash-verified lock file.

| Package | Resolved version |
| --- | --- |
| streamlit | 1.64.0 |
| a2a-sdk | 1.1.2 |
| uvicorn | 0.53.0 |
| azure-identity | 1.25.3 |
| azure-appconfiguration | 1.9.0 |
| openai | 3.14.1 |
| textstat | 0.7.13 |
| nltk | 3.10.3 |

### Completed implementation checks

- **32 PoC001 tests passed** on the VM: existing A2A/runtime contracts plus
  single-identity selection, no legacy credential fallback, invalid/missing IDs,
  unchanged default full-mode validation, early backend operation rejection,
  context refresh, empty-profile failures, GPT-4o request payloads, Streamlit UI
  isolation/generation/feedback/refresh and Windows launcher validation.
- **10 shared hosting tests passed** using the PoC001 venv and the unchanged
  cross-platform `deployment/redhat/tests/test_hosting.py` suite. Both standalone
  hosting helpers remain byte-identical. This is not a systemd/Bash deployment
  validation or a PoC002 dependency/environment test.
- Model, configuration and audit calls in these tests were mocked; no Azure
  token requests, inference or configuration writes were needed.
- Editor diagnostics, Git whitespace checks and local deployment-document link
  validation passed. Upstream A2A protobuf deprecation warnings and Streamlit
  test-harness context warnings did not fail tests.

### Completed localhost startup

- Created a new private `C:\ProgramData\elv\poc001` directory with inheritance
  disabled and access limited to the operator, SYSTEM and Administrators.
- Populated external nonsecret `runtime.json` and created its separate state
  directory. The JSON inherited the three intended private access rules. No
  app-registration secret or credential cache was copied into configuration.
- The actual runtime JSON returned `CONFIGURATION_VALID` in validate-only mode,
  with no token request or Azure call. Syntax validation does not prove that the
  reported identity UUID is the Client ID of the attached managed identity.
- Started both components using the Windows launcher. The UI terminal stopped
  once after initial startup, causing the reported connection refusal. Only the
  missing UI component was restarted; the existing agent was left running.
- Subsequent checks returned agent `/health` = `ok`, UI `/_stcore/health` = `ok`,
  and UI root HTTP **200**. Both listeners were observed on **127.0.0.1 only**:
  agent port 9999 and UI port 8501.

The current viewing address is <http://127.0.0.1:8501> **in the VM's browser**.
The terminal processes must remain running. Windows service installation,
sign-out/reboot recovery, firewall/NSG changes and shared HTTPS publishing were
not performed.

### Approved configuration initialization (2026-09-16)

The store was empty at the initial localhost handoff. A separate
[initializer](../../deployment/windows/initialize_config.py) was then added with
a local-only preview and explicit apply/approved-host gates. The user reviewed
the proposed scope and approved applying the 12 synthetic baseline/candidate
entries to the configured existing store using its attached managed identity.

The approved run returned:

```text
INITIALIZATION_SUCCEEDED: 12 verified; created=12; preserved=0.
```

All 12 exact experience key/label pairs were checked before writing, created
using the SDK's atomic create-only operation, and read back successfully. This
demonstrates authentication and effective create/read access by the explicitly
configured managed identity on the selected store, not an inventory of all role
assignments or proof of least privilege. No existing values were overwritten,
and no role, resource, index, deployment or document was changed. Initialization
is not invoked by startup; it remains an explicit approved operator action.

Nine initializer tests cover preview without credentials/API activity, apply
approval, explicit identity selection, inherited-secret rejection, exactly 12
creates/readback, matching reruns, existing conflicts, concurrent conflicts and
partial failure without deletion. **All 41 PoC001 tests passed** after this
addition. Editor diagnostics and Git whitespace validation passed; both localhost
health endpoints still returned `ok`. The earlier ten shared hosting checks
remain separate evidence from the initial Windows implementation.

### User-confirmed live comparison (2026-09-16)

After initialization, the user tested the comparison UI and reported that both
responses returned successfully. This is user-run evidence of the basic live
baseline/candidate workflow with the configured GPT-4o deployment. It is not
an assistant-executed inference test or an assessment of response quality.
No additional model requests or Azure changes were made to record this result.

The basic localhost comparison has therefore succeeded end to end for this
test. Configuration refresh after a deliberate approved change to a real profile
has not yet been reported or verified.

### Remaining refresh and publication gates

Select **Refresh configuration from Azure** before generating a comparison so
cached empty profiles are discarded. No process restart is required for the
new settings. The ordered commands and failure behavior are documented in the
[Windows runbook](../../deployment/windows/README.md#explicit-initializer).

The initializer itself made no model requests. Live generation now has the
user-confirmed evidence above; refresh against a changed real profile remains
the outstanding part of T024. T025 remains open for separately approved
private-IP HTTPS and persistent Windows hosting, including restart/reboot
recovery. Search, audit and authentic multi-persona RBAC remain outside the
approved reduced milestone.

## Local configuration editor — 2026-09-17

The customer deferred shared networking/HTTPS and chose VM sign-in plus local
browser access. The future administrator handoff is retained in the
[Windows runbook](../../deployment/windows/README.md#7-shared-private-https-administrator-handoff),
explicitly marked deferred. No IIS, DNS, certificate, firewall, NSG or role
changes were made. T025 is not a current prerequisite for local viewing/editing.

The user requested direct editing of the populated App Configuration values
using the existing managed identity. Added `ELV_ENABLE_CONFIG_EDITING` as an
explicit runtime JSON option, default false; enabled it in the protected local
configuration. It adds a Configuration tab for the six known experience keys
in the baseline/candidate profiles. There is no separate approver or draft
store: saves are live, use the same runtime identity, and require effective
App Configuration write permission.

### Verification

- **59 PoC001 tests passed**, including 18 new editor tests for opt-in/default-off
  policy, exact targets, metadata preservation, stale/concurrent/deleted settings,
  invalid values, preserved disabled operations, UI loading/saving/conflicts,
  profile/asset selection, discarded unsaved text on reload, cleared response
  contexts, and authoritative runtime JSON activation.
- **10 shared hosting tests passed** after the backend/launcher changes.
  The default full-governance identity validation and identical hosting helpers
  remain intact. `pip check` reported no broken requirements.
- The actual external runtime JSON passed validate-only with editing enabled,
  without credentials or Azure requests. The UI was restarted to load the code
  and option; the existing response agent remained running.
- Browser inspection at localhost showed Experience comparison and Configuration
  tabs, with no persona, draft, audit or Search controls. Selecting **Load current
  value** successfully retrieved the existing candidate `experience:tone` from
  Azure using the configured managed identity, with a populated value field and
  the explicit **Save to Azure** command.
- Agent and UI health returned `ok`, UI root returned HTTP 200, and listeners
  remained 127.0.0.1:9999 and 127.0.0.1:8501 respectively.

No Azure setting was changed by this editor rollout or browser inspection and no
additional model request was made. Saves and conflict cases were tested with
mocked Azure clients; the real load is separate live-read evidence. T030 and the
refresh-after-change portion of T024 remain pending a user-chosen save and a
subsequent comparison. After a successful save, the saving session automatically
clears cached profiles, old results and A2A context IDs; other open sessions
must refresh to leave their intentionally pinned contexts.

The backend uses an exact existing key/label plus the loaded ETag and
`MatchConditions.IfNotModified`; it does not create missing settings, overwrite
a stale version, expose generic writes or enable the full governance workflow.
All local users share the identity's actual Azure privileges. This UI restriction
is not per-user authorization or an Azure label-level RBAC policy.

## Existing-index RAG — 2026-09-18

The user selected `medical-policies-vector` and explicitly approved all documents
in that index for retrieval and excerpt transmission to the existing GPT-4o
deployment. This supersedes the earlier exclusion of Search for the initial
comparison milestone, but does not reopen shared networking, audit or multi-role
governance. Other indexes and unapproved data remain outside the selected scope.

### Read-only discovery and preserved resources

- The schema GET with the existing managed identity returned HTTP 403 and was
  stopped. No role was granted or alternate credential used. The user supplied
  the schema fields, including Title, Content, Status, State and ContentVector.
- Zero-document queries accepted the Title/Content search fields and selected
  title/text/status/state/date/source metadata. Separate zero-document filters
  on Status and State also passed. No document text was retrieved by those probes.
- Bounded zero-document facets returned Status values Reviewed, Revised and New;
  State included state codes and the non-geographic value `medical-policies`.
  These are observed metadata values, not independently verified approvals or
  an immutable inventory. The runbook gives exact-case example filters.
- No Search schema, content, vectors, indexer, alias, CMK, identity attachment,
  role, network, certificate or IIS setting was changed. ContentVector's
  1,536-dimensional data is not used by this initial keyword query path.

### Approved configuration and functional test

Added the explicit RAG opt-in, approved Search endpoint and exact index allowlist
to protected external runtime JSON. The separate knowledge profile maps Content,
Title, Status, State, PublishDate and BlobName; absent sample fields are omitted.
The initial blank filter reflects approval of the whole selected index. Both
profiles start with `top_k=3`, `query_mode=simple` and inline citations.

The user approved the previewed 32 knowledge settings and one grounded comparison.
The knowledge-only initializer returned:

```text
INITIALIZATION_SUCCEEDED: 32 verified; created=32; preserved=0.
```

Only missing baseline/candidate `knowledge:*` entries were created and read back;
existing experience values were not touched. Startup still never seeds Azure.
Both UI and agent were restarted with RAG enabled. Health checks returned `ok`
and listeners stayed on 127.0.0.1:8501 and 127.0.0.1:9999.

The approved browser test enabled **Ground with AI Search** and submitted
`What documentation is required to establish medical necessity?` once. Both
baseline and candidate responses completed and displayed **Sources (3)** panels.
This is live evidence of configured text retrieval, excerpt transmission to
GPT-4o, A2A response handling and source-metadata display with the existing index.
It consumed the normal two model requests; no load/retry loop was run. The
initial excerpt limit was three chunks of up to 2,500 characters per request.
No raw document excerpts or generated policy answers are copied into this record.

### Offline validation and limits

- **86 PoC001 tests passed**, including configurable mappings, exact filter
  preservation, bounded/missing content, explicit opt-in/index restrictions,
  no-model behavior on zero matches, pinned knowledge contexts, version-safe
  knowledge edits, grounded UI calls/citations and knowledge-only initialization.
- **10 shared hosting tests passed**; default full-mode identity/audit contracts
  and identical standalone hosting helpers remain intact. `pip check` passed.
- Editor diagnostics and Git whitespace checks passed before deployment.
- Final runbook link/whitespace checks and editor diagnostics passed. Browser
  inspection also confirmed the Knowledge configuration area and a successful
  read of the current candidate `knowledge:filter` into its editable value field.
  The filter remained blank; no editor save or further model request was made.

This is keyword RAG over an index that also contains vectors, not vector or
hybrid search. Semantic ranking, embedding compatibility, other indexes and
document-level authorization were not validated or enabled. The user approved
whole-index access for trusted local users. Configuration filters select content
but do not authenticate users. Source presence does not establish completeness,
medical/coverage correctness, resistance to all prompt injection or response
quality; those require a suitable evaluation set and human review.

Live filtered comparisons and later user changes to knowledge values were not
performed. The initial filters are blank; changing them remains an explicit
version-checked UI save. Shared networking/HTTPS remains deferred.

## VM and healthcare merge reconciliation — 2026-09-22

The user authorized repairing merge `d706a82` while retaining the incoming
healthcare prompts and RAG configuration changes on the already configured
Windows VM. This record describes the repaired working tree, not the original
merge commit and not a redeployed/live acceptance result.

### Reconciled behavior

- Restored configuration imports, conflict exceptions and comparison-mode
  restrictions while retaining the full demo's mutation/history implementation.
- Corrected UI generation arguments and restored mutation-result notices.
  Grounded and ungrounded modes use the same healthcare member-support question.
- Reused the shared Search normalizer, retaining explicit blank filters and the
  existing index's case-sensitive field mappings. Removed duplicated merge blocks.
- Restored healthcare provenance/privacy rules and runtime tests lost during the
  merge. Full-demo previews and strict VM no-source/opt-in behavior both remain.
- Integrated the shared six-control Search form in the VM's Configuration tab,
  using the existing production store and managed identity. It validates before
  writing, checks versions, preserves mappings and reports partial saves. No
  draft store, new identity or Blob history is implicitly required on the VM.

### Executed verification

- **236 PoC001 tests passed** against actual repaired source, including prompt,
  Search normalization/mapping, both runtime modes, UI, ETag, partial-save and
  history behavior. No missing source definitions were injected for this run.
- **22 shared hosting/deployment contract tests passed**, including the incoming
  audit-backend launcher contracts. These are offline Python/static/mock checks,
  not live Linux/systemd deployment acceptance.
- The PowerShell seed suite returned **PASS: offline seed configuration tests
  (function-mocked CLI)**. Its mock writes do not touch Azure.
- The existing external runtime JSON returned `CONFIGURATION_VALID`; validation
  did not fetch tokens or call Azure. Dependency checks passed in the isolated
  test environment. Editor, whitespace and documentation-link checks passed;
  no conflict markers or implementation extension hooks remained.

The active PoC venv did not contain the incoming `azure-storage-blob` dependency.
For these tests, version **12.30.2** was installed only in a temporary dependency
overlay and supplied through process-local `PYTHONPATH`. The live venv, runtime
JSON, Azure resources/values and running UI/agent processes were not modified or
restarted. The temporary overlay is not a substitute for deploying requirements.

### User local acceptance

Follow [the merged-checkout instructions](../../deployment/windows/README.md#test-an-updated-or-merged-checkout):
stop both processes, install matching requirements into the existing PoC venv,
validate the same runtime file and restart both with the Windows launcher.
Do not rerun initializers merely to apply new sample personas/filters. Previously
saved Azure values remain authoritative and should be edited only deliberately.

T041 remains open for the user's real comparison, grouped Search load/save,
refresh and citation checks. No live inference, Search retrieval, configuration
write, Blob access, permission change or network operation was performed by
this merge repair. Shared networking remains deferred.

## Search diagnostics and inline citations — 2026-09-22

The user reported an A2A task failure after saving a filter. Existing agent logs
identified Search HTTP 400: the earlier filter referenced missing `industry`,
then missing lowercase `status`. The selected index uses `Status`/`State`.
The user's later screenshot showed the corrected `Status ne 'Revised'` value.
No filter was removed, rewritten or saved by this investigation.

The user also supplied configuration/provenance screenshots with inline citation
style, grounded prompt asset `response:v3`, and three retrieved-source rows but
no inline markers in the answer. A read of that already-completed local task
confirmed a nonempty response without `[n]` markers. The first task GET lacked
the A2A version header and returned 400; the corrected GET with `A2A-Version: 1.0`
returned the existing artifact. No new task or model request was sent. The old
artifact did not report pinned citation style, so the current settings alone
could not establish which style that prior context had applied.

Implemented safe HTTP 400 configuration guidance and an A2A task-error type so
this failure is no longer presented as a disconnected agent. The VM form no
longer shows the sample index's incompatible filter as an example/default.
The requested filter remains intact and is never broadened to recover a query.

Inline-mode answers now require at least one numeric source marker and no
out-of-range marker numbers. Nonempty model output failing that check is withheld
with `citation_validation_failed`, not assigned fabricated references or retried.
Applied `citation_style` and `citation_status` travel with the A2A task, and the
UI labels the table **Retrieved sources**. This checks format and source numbers,
not claim support, source relevance, marker placement for every statement or
medical correctness. Footnote-style compliance is not claimed as validated.

**242 PoC tests and 22 shared hosting/deployment tests passed** offline, including
Search-error propagation with no filter removal/model call, uncited-output
withholding, valid marker preservation, none-mode behavior and A2A/UI provenance.
`pip check` and changed-file editor diagnostics passed. No real Azure values,
permissions, indexes, document content or deployment settings were changed;
no additional inference was run. Live behavior after local restart remains a
user acceptance check, not a claimed new successful cited response.

Both known local PoC processes were subsequently restarted through the unchanged
Windows launcher/runtime JSON. Agent and UI health returned `ok`, UI root returned
HTTP 200, and ports 9999/8501 remained bound only to 127.0.0.1. This activates the
new behavior for future tasks; restarting clears in-memory contexts and does not
retroactively cite the earlier response. No new inference was made after restart.

## VM configuration history implementation — 2026-09-22

The user approved connecting local configuration edits to the existing Blob
history recorder, reusing the VM runtime managed identity for both writes and
reads. The selected target is the existing `tenxengbenefitaistandard` account
and a dedicated private `poc001-config-history` container. The user reported that
the container needs creating and selected **implementation only**, with the live
test to be performed by the user. No container, role or network change was made.

### Implemented scope

- Added the explicit default-off `ELV_ENABLE_CONFIG_HISTORY` runtime option.
  Comparison history uses only the configured runtime client ID; full-demo
  separate writer/reader validation remains intact. The Windows launcher
  validates nonsecret targets locally and prevents inherited settings from
  silently enabling history or switching it to Log Analytics.
- Version-checked live saves record known before/after values and ETags, bounded
  key/profile identity, operation ID and actual result through the existing
  create-only recorder. No-op saves do not write events. Grouped Search writes
  share an operation ID and preserve history warnings alongside partial outcomes.
- Configuration failures keep their original type and outcome. A write timeout
  remains unknown. Blob failures cannot retry, roll back or hide a confirmed
  configuration change. Both successful single-key saves and failures surface
  their separate history warnings in the UI.
- Added history support for the VM's field-mapping keys without broadening the
  full-demo edit allowlist. No model questions, responses, document excerpts,
  tokens or raw provider errors are added to events. No historical backfill.
- The optional Change history tab uses the existing bounded reader/export code.
  It performs no read until Refresh is selected and reports outages as unavailable,
  not empty successful history. It explicitly identifies the shared VM identity;
  this is not authenticated human attribution or tamper-proof storage.

### Completed offline and local checks

- **261 PoC001 tests and 22 shared hosting/deployment tests passed**. New checks
  cover default-off behavior, explicit shared identity selection, staged/invalid
  settings, before/after preservation, no-ops, conflicts, read/write timeouts,
  history failure isolation, grouped IDs, history reads and save warning display.
- Storage clients/transports and Azure configuration writes were mocked. No live
  Blob list, upload, download, synthetic event, App Configuration change, Search
  query or model request was made for this implementation.
- `pip check`, editor diagnostics and documentation link/whitespace validation
  passed. The external runtime JSON was staged with the approved account/container
  and `ELV_ENABLE_CONFIG_HISTORY=false`; validate-only passed without token requests.
- Only the local UI was restarted with history disabled; the existing agent
  stayed running. Both health endpoints returned `ok`, the UI root returned
  HTTP 200, and listeners remained loopback-only on ports 8501 and 9999.

### Activation status at the implementation checkpoint

At this checkpoint T048 remained open. An authorized owner needed to create/confirm the private container
and effective read/create access for the existing VM identity. The user can then
set the flag to `"true"`, restart the UI, make an intentional non-sensitive
configuration edit, and verify its event through Change history or the container.
The exact [activation steps](../../deployment/windows/README.md#configuration-change-history-in-blob-storage)
are documented. Container existence, Blob permissions/network access, retention
and actual live history persistence had **not** been verified at this checkpoint.
The later [activation and user acceptance](#history-activation-and-user-acceptance-2026-09-23)
record below supersedes that status, not the historical test results.

## History container setup script — 2026-09-22

Added the requested [prepare_history.py](../../deployment/windows/prepare_history.py)
operator script. It uses the existing external runtime JSON and explicit VM
managed identity. The default is a local-only preview; applying requires both
`--apply` and `--approved-azure-host` on Windows with the PoC venv interpreter.

The apply path creates only the named container when it is missing, with no
anonymous access, then verifies its properties. Existing private containers are
preserved; public containers are rejected without access-policy changes. Only
after verification is `ELV_ENABLE_CONFIG_HISTORY` set to `"true"` in local JSON,
preserving all other values through a Windows replacement operation. Concurrent
edits detected during setup stop the update. This does not claim an atomic
cross-service transaction or compare-and-swap against simultaneous local writers.

**273 PoC001 tests plus 22 shared hosting/deployment tests passed.** The 12 new
script tests cover preview/approval, missing targets, create-only privacy,
private reuse/idempotence, create races, public targets, permission/verification
failures, credential rejection, concurrent edits and local replacement failure.
Azure identity/Storage operations were mocked. Local replacement was exercised
on temporary Windows files, not on the active runtime file.

The actual no-apply preview displayed the staged account/container and intended
flag. SHA-256 before/after checks confirmed the real runtime JSON was unchanged;
the history flag remained `"false"`. `pip check`, editor diagnostics, links and
whitespace checks passed. No new packages, process restart, Azure request,
container, blob, role, network setting or model request was made in this step.

T049-T050 were complete at the preview checkpoint; T048 was pending the separately
authorized apply and live history test. Creating/reading container properties does not prove future event
upload/list/download permission. A created container can remain if a later local
update fails; the script does not roll back or delete it. The
[scripted activation instructions](../../deployment/windows/README.md#scripted-container-setup-and-local-activation)
include permission prerequisites, restart steps and failure handling.

## History activation and user acceptance (2026-09-23)

This dated update supersedes the staged-disabled/pending-container status above.
It does not imply that the earlier offline runs included live Azure operations.

| Date and source | Operation or observation | Evidence scope |
|---|---|---|
| 2026-09-22, explicit user request and observed script result | Ran the separate history setup with `--apply --approved-azure-host` | `CONTAINER_CREATED_PRIVATE` and `HISTORY_ENABLED` for `tenxengbenefitaistandard/poc001-config-history`; runtime JSON flag set to true using the existing managed identity |
| 2026-09-22, observed UI-only restart | Launcher validation passed; new UI process loaded the updated settings | UI/agent health returned HTTP 200; listeners stayed on loopback. The agent was unchanged in this history-only restart |
| 2026-09-23, user confirmation during documentation review | Blob history configuration save/readback verified | Successful history path is user-confirmed, not independently repeated by the assistant or supported by new event contents/screenshots in this record |

The setup did not change roles, networking, account settings or existing blobs
and uploaded no test event. Successful create/property checks and the subsequent
save/readback do not inventory effective role assignments, prove container-only
access, verify Private Link, establish immutability, or approve retention.
T048's successful preparation/save/readback scope is complete. T051 retains
role-scope, retention and live warning-path review. Do not infer completion of
configuration-to-model refresh tests from the history test alone.

## Citation abstention deployment (2026-09-22)

The prompt/runtime contract now distinguishes an exact `NO_SUPPORTED_ANSWER`
from uncited substantive model output. The former produces a safe
`insufficient_evidence` result; extra uncited advice and invalid inline source
numbers remain withheld. The check does not establish claim-level support.
The latest recorded **276 PoC001 offline tests passed**, including rendered
prompts, abstention and A2A provenance. The agent alone was then restarted;
UI/agent health returned HTTP 200 and both remained loopback-only. No new model
or Search query was submitted by the assistant to verify this deployment.

Stored pre-restart tasks showed missing inline markers for the default appeals
question and medical-policy source titles. Rejected drafts were not retained,
so the exact text cannot establish whether a particular failure was an uncited
answer or a legitimate refusal. Neither source titles nor passing marker syntax
prove that the corpus contains a suitable answer. Existing displayed results
are not rewritten by this change.

## Documentation review scope (2026-09-23)

The user confirmed an existing corpus of hundreds of thousands of **source
documents**, including medical policies in Blob Storage and administrative
guidance/forms/FAQs. Metadata quality, resulting chunk counts and full inclusion
in the current query scope are unassessed. The approved documentation describes
both shared and caller-specific retrieval, without choosing a new deployed
security model. PoC002 code exists but live end-to-end verification remains
unconfirmed. Proposed multi-agent coordination is read-only guidance, not
clinical decisions, claims access or appeal submission.

Documentation edits and their checks do not provision resources, change runtime
settings, rerun application tests or establish new inference/scale results.

### Documentation implementation checks

The 2026-09-23 update changed nine existing Markdown files only: the two design
documents, two PoC READMEs, Windows and Storage runbooks, and this feature's
plan/tasks/validation records. No application code, prompt asset, runtime JSON,
dependency, Azure service, identity permission or running process was changed.

- Local link targets, 21 Markdown heading anchors, balanced code fences,
  conflict markers and `git diff --check` passed. Editor diagnostics reported
  no errors in the edited documents.
- All eight Mermaid blocks across the two design documents parsed and rendered
  using Mermaid 11.4.1 in a separate `about:blank` browser page. Normalized source
  fingerprints matched the Markdown blocks. A sequence-label syntax defect was
  corrected; wide flowcharts were reorganized for readable document-width
  rendering, and the coordinator's group-title overlap was removed.
- The targeted stale-claim scan found no remaining current-state assertions
  that history is staged/disabled, PoC002 is unbuilt, or a sentinel makes writes
  atomic. Historical checkpoints remain explicitly dated and superseded.
- A documentation-only walkthrough checked the proposed paths below. These are
  design checks, **not execution tests of an implemented coordinator or index**.

| Review case | Documented behavior |
|---|---|
| Simple versus compound request | Single-capability path or bounded approved subtasks, with one final presentation persona |
| Missing plan/date or inadequate evidence | Clarify or decline; do not infer eligibility, fabricate citations or widen mandatory scope |
| Required/optional specialist failure | Block dependent advice or explicitly label independent supported portions |
| Conflicting source versions or indirect instructions | Reviewed authority/version policy or unresolved outcome; retrieved text cannot grant tools/access |
| Caller-specific content | Enforce scope on queries, chunks, lookups, caches, artifacts, facets and source downloads |
| Missing tags, obsolete chunks or schema evolution | Metadata assessment, authoritative correction, propagation/backfill and evaluated cutover/rollback |

T052-T056 are complete. T051 and the independent hosting/security/quality gates
remain open. The 276-test result above is historical application evidence, not
a new test run for this documentation-only change. No new Blob event, Search
query, model request, load test or PoC002 deployment was performed.