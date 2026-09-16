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