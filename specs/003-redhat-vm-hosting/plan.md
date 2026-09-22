# Implementation plan: Red Hat VM hosting

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