# Red Hat Azure VM hosting — both PoCs

**Status:** Source implementation; target VM execution and Azure validation are
pending. This is a trusted presenter deployment, not a production multi-user app.

Both UIs are headless web applications. No server desktop or GPU is needed.
Application execution, package installation and tests below happen **on the VM**.
Only the browser/SSH client runs on the approved workstation in this runbook.
The launcher is **Linux-only** and does not start applications on Windows.
For a separately approved Windows development run, use the
[PoC001 application instructions](../../pocs/001-config-driven-responses/README.md#run-on-windows-development).
PoC001 defaults to Blob application history with **no Log Analytics dependency**;
PoC002 retains its required legacy Log Analytics configuration.

## Boundaries: read before installing

- Use a dedicated or equivalently trusted RHEL VM in the target tenant. **All
  code/users on a VM can potentially access its attached managed identities.**
  Two Linux users and two virtual environments are operational separation, not
  managed-identity security boundaries. Do not place untrusted workloads here.
- Presenters can select all demo personas. SSH access authenticates a presenter;
  the persona selector does not authenticate or authorize real end users.
- Never put credentials in chat, source, URLs, command arguments or copied logs.
  The configuration examples contain only endpoints and identity/resource IDs.
- Do not copy old dotenv, persona secrets, virtual environments, CLI token caches,
  SSH keys or generated feedback from the workstation to the VM. Deliver an
  approved **source-only** checkout/artifact of these changes.
- This package does not create, seed, patch or delete Azure resources. **Do not
  run the PoCs' existing setup/governance/knowledge/teardown scripts unchanged
  against shared services.** They provision/overwrite resources and can reset
  app credentials or delete a whole resource group. Safe Azure reuse/seeding
  remains a separate approved step.
- Do not open application ports on the NSG, host firewall or public interface.
  Do not disable TLS verification, CORS/XSRF protections, SELinux or FIPS policy.

## 1. Readiness gate

Obtain nonsecret VM details: RHEL version, architecture, vCPU/RAM/disk, supported
Python, install approval, VM tenant/subscription, trusted workload status and
approved SSH/VPN/Bastion route. RHEL 8/9/10 are the initial targets. Prefer an
approved Python 3.11/3.12; the application minimum is 3.10. About 2 vCPU/8 GiB is
a sizing starting point, not a tested requirement.

An administrator must make approved Python/venv/pip, Git, Bash, curl and systemd
available. Use approved package mirrors and CA certificates. Azure CLI and
PowerShell 7 are only needed for operator-side Azure work, not steady-state
services. PowerShell's existing minimum-version header does not require Windows;
retain PowerShell 7 rather than rewrite all Azure scripts into Bash.

On the VM, from the delivered checkout (substitute the approved interpreter):

```bash
/usr/bin/python3.12 deployment/redhat/preflight.py --json
```

[preflight.py](preflight.py) reads host metadata and checks loopback ports. It
does not install packages, import either PoC, sign in, request a token or make an
Azure API request. Exit 1 means a required local prerequisite failed. WARN/INFO
items still need operator review; an exit 0 is **not** Azure deployment approval.

Separately confirm:

- Approved package downloads and SSH reachability; no credential-bearing URLs.
- VM DNS/routing/HTTPS to App Configuration, OpenAI and Search, plus Blob for
  PoC001 history, Language for PoC002, and Monitor for PoC002 or explicit PoC001
  Log Analytics mode; private endpoint DNS/peering as required. Knowledge
  onboarding also needs its separately approved Blob path.
- IMDS access at 169.254.169.254, bypassing proxies. Merge the examples' NO_PROXY
  values with approved existing bypasses; do not replace required enterprise CA
  or proxy configuration. Browser-to-VM connectivity does not prove Azure access.
- **Search indexer-to-Blob** identity/network access independently of VM egress.
- RHEL package/FIPS/SELinux compatibility. Resolve denials with the administrator,
  rather than disable enforcement. Source execution from /opt/elv must be allowed.

## 2. Ready Azure resources and permissions (administrator)

Supply an approved mapping before starting services. Runtime environment files
are deliberately incomplete templates: required normal settings fail validation
until filled in; PoC001 Blob settings instead use the warning boundary below.

| Dependency | Required mapping / preparation |
|---|---|
| App Configuration | Distinct live/draft stores for each PoC and their endpoints. Full audit ARM IDs are required only for PoC002 or PoC001 explicit Log Analytics mode. Do not share unchanged stores between PoCs: baseline keys collide. |
| OpenAI | Existing compatible Azure OpenAI endpoint, deployment name, model/API version and sufficient quota. Both PoCs may share one deployment. A Foundry project URL is not a substitute for the account endpoint used by this code. |
| Search | Existing suitable service, approved content and compatible schemas/indexes or aliases. The repository sample layout uses four indexes combined (1 + 3); do not build/rebuild them automatically on customer services. Preserve existing index selection and each language's analyzer. |
| Knowledge Blob | Approved PoC-only source containers and working indexers; prefer Search-to-Blob managed identity on a suitable tier. Keep history separate from indexed knowledge. No storage key fallback is implemented by hosting. |
| Language | PoC002 custom-subdomain endpoint supporting Entra authentication and language detection. Required for the selected full demo. |
| PoC001 history (default) | Private, owner-precreated `poc001-config-history` container at `https://tenxengbenefitaistandard.blob.core.windows.net`, separate writer and reader identities, approved VM-to-Blob access. No workspace UUID, resource-log ARM IDs or Monitor queries required. |
| Legacy Log Analytics | Required for PoC002 regardless of `ELV_AUDIT_BACKEND`; optional for PoC001 only with `ELV_AUDIT_BACKEND=loganalytics`. Existing workspace customer UUID, both store ARM IDs, AACAudit/AACHttpRequest diagnostics, resource-context query authorization and verified ingestion. |
| Identity | Distinct managed-identity **client IDs**, not principal/object IDs, attached to the target-tenant VM; full resource IDs/object IDs retained separately for administrators. |

Create/reuse four persona identities for 001 and five for 002, **plus a dedicated
audit reader identity for each PoC**. PoC001 Blob mode additionally needs an
explicitly selected writer UAMI distinct from every persona and the audit reader.
Do not grant one identity all personas' rights. No identity creation or
role-assignment commands are run by the installer or application.

| Identity | Scope and minimum intended permissions |
|---|---|
| Viewer | App Configuration Data Reader on that PoC's live and draft stores |
| Designer | Data Reader on live; Data Owner on draft |
| Market owner (002) | Same as designer; Azure still does not enforce locale-specific labels |
| Approver | Data Owner on the two PoC-only stores |
| App | Data Reader on live only; Cognitive Services OpenAI User on approved OpenAI resource; Cognitive Services Language Reader on Language for 002 |
| Querying personas | Search Index Data Reader for approved PoC indexes, verifying alias access and role scope; never broad access to unrelated confidential content |
| PoC001 history writer (`ELV_AUDIT_BLOB_WRITER_CLIENT_ID`) | Storage Blob Data Contributor on **only the dedicated history container** |
| PoC001 history reader (`ELV_MI_AUDIT_CLIENT_ID`) | Storage Blob Data Reader on **only that history container**; no upload grant |
| Legacy audit reader (PoC002; PoC001 opt-in) | Resource-context log-query rights only on the two approved stores, with the workspace access-control mode configured to support them |
| Search indexer identity | Storage Blob Data Reader on assigned PoC containers |

Use direct resource assignments where appropriate and allow propagation. Do not
give runtime identities provisioning rights. An administrator can perform scoped
setup separately using their approved MFA workflow. Direct VM managed-identity
access assumes the resource tenant is compatible; changing AZURE_TENANT_ID does
not move a VM identity into another tenant.

### PoC001 Blob history boundary

Set `ELV_AUDIT_BACKEND=blob` (also the default when absent),
`ELV_AUDIT_BLOB_ACCOUNT_URL`, `ELV_AUDIT_BLOB_CONTAINER` and the separate
`ELV_AUDIT_BLOB_WRITER_CLIENT_ID` using [poc001.env.example](poc001.env.example).
Reuse `ELV_MI_AUDIT_CLIENT_ID` for reads. The account URL is the standard HTTPS
Blob hostname, without a SAS/query, embedded credentials or container path.
The owner must precreate/approve the **private** container and scoped grants;
neither service creates/overwrites containers or changes cloud permissions.
Do not grant account-, subscription- or root-wide access for this feature.
Prefixes are not RBAC isolation. See the
[storage history prerequisites](../storage/README.md#poc001-application-change-history).

History is best-effort application-recorded before/after configuration evidence,
not a compliance audit system. Missing/invalid Blob settings, an invalid or
colliding writer UUID, denied storage access or timeout must produce a visible
warning without replacing the App Configuration outcome or blocking generation.
There is no automatic Log Analytics fallback, local outbox or historical backfill.
Normal persona/audit-reader UUID validation, App Configuration authorization and
conflict checks still apply; fail-open history does not bypass them.

One create-only JSON block blob is attempted per event. It is **not immutable**:
Contributor can overwrite/delete blobs, and a crash between configuration write
and history upload can leave a gap. Only app operations are covered, not direct
Portal/CLI edits, seeds or provisioning. Persona/client ID describes the acting
service credential, not an authenticated human. Store no PHI, tokens or secrets
in configuration; before/after values are recorded. The history reader supports
bounded selections and CSV export; unavailable/partial results must be visible,
not presented as a complete record. Retention remains an owner-managed policy.

Deploy the matching application/UI/mutation integration and verify warnings,
before/after display and CSV in acceptance; the helper modules and launcher
change alone do not establish end-to-end history. New code/dependencies and
environment settings need deployment and service restart. Existing App
Configuration values require a reviewed migration; no automatic reseed occurs.

### Legacy Log Analytics only

VM Log Analytics calls use resource-context queries, not broad workspace queries.
If the existing workspace/table setup does not permit that mode, arrange an
approved logging design. Do not grant workspace-wide read merely to suppress a
403. Validate ingestion with an approved PoC write/denial. This applies to
PoC002 regardless of the backend environment value, and to PoC001 only on
explicit opt-in; Blob failure never switches modes automatically.

Demo configuration, compatible indexes, approved documents and the chosen
history prerequisites must be supplied by their owners. Do not run the legacy
provisioners against customer services to fill gaps. Review any PoC001 seed
migration using the [scoped seed behavior](../../pocs/001-config-driven-responses/README.md#seed-and-migrate-existing-configuration)
before applying it; seed changes are outside application history.

## 3. Prepare the two Python environments

Deliver the source at **/opt/elv**, owned by a trusted non-root deployment
operator, with readable/traversable nonsecret source directories. Do not use a
checkout under a home directory: services deliberately use ProtectHome=true.
The service accounts must not be able to modify source or dependencies.

As the deployment operator on the VM:

```bash
cd /opt/elv
bash deployment/redhat/prepare-environments.sh /usr/bin/python3.12
```

[prepare-environments.sh](prepare-environments.sh) runs the readiness checker,
creates a .venv in each PoC, installs that PoC's requirements, runs pip check and
records resolved versions in a gitignored inventory in that project. It does
not start applications or change Azure. It refuses root execution; it does not
install into system Python. Public dependency files use a readable umask so the
non-login service users can access them. Do not place secrets in those venvs.

Dependencies currently use the repository's version ranges. Target installation
and contract tests, especially A2A/Streamlit/Azure SDK behavior, are a release
gate. The generated version inventory is evidence, **not** a hash-verified lock.
After validation, retain the exact resolved versions/approved wheels with the
deployment artifact. Stop services before subsequent dependency updates.

## 4. Run the offline checks on the VM

These tests use mocks, not Azure credentials. Run shared contracts in **both**
venvs to catch dependency differences. PoC001 tests need its working directory.

```bash
cd /opt/elv
bash -n deployment/redhat/prepare-environments.sh
bash -n deployment/redhat/install-services.sh
pocs/001-config-driven-responses/.venv/bin/python -m unittest discover -s deployment/redhat/tests -v
pocs/002-regional-multilingual-experience/.venv/bin/python -m unittest discover -s deployment/redhat/tests -v
cd /opt/elv/pocs/001-config-driven-responses
.venv/bin/python -m unittest discover -s tests -v
```

Do not continue if any test fails. These tests do not establish Azure access,
network reachability, systemd behavior or full functional acceptance.

## 5. Install services, then configure (administrator)

Preview first; --apply is required for host changes:

```bash
cd /opt/elv
bash deployment/redhat/install-services.sh
sudo bash deployment/redhat/install-services.sh --apply
```

[install-services.sh](install-services.sh) creates non-login users elv-poc001 and
elv-poc002, private state directories, three systemd units and initial environment
files. It preserves existing environment files, refuses unowned unit names,
checks basic service-user read/execute and source write permissions, verifies
units and reloads systemd. It **does not** start or enable services, run pip,
change a firewall or call Azure. Failure can leave installed host files/users;
correct the reported issue and rerun. It is not a transactional OS installer.

Complete the installed files using an approved editor:

```bash
sudoedit /etc/elv/poc001.env /etc/elv/poc002.env
sudo chown root:elv-poc001 /etc/elv/poc001.env
sudo chown root:elv-poc002 /etc/elv/poc002.env
sudo chmod 0640 /etc/elv/poc001.env /etc/elv/poc002.env
```

Use the structure of [poc001.env.example](poc001.env.example) and
[poc002.env.example](poc002.env.example). Values are literal systemd KEY=value
assignments, **not shell commands**; no export, command substitution or dotenv
interpolation. Never source the template in a shell. Configure distinct stores,
all required endpoints, identity IDs and existing deployment name. Supply
workspace UUID and audit resource IDs only for the LA paths described above.
Keep placeholder values out of the live configuration.

The launcher forces azure-vm mode regardless of environment-file settings,
validates normal endpoint/tenant/model/state settings and the persona/audit-reader
map without token requests, and uses only explicit managed identities. It checks
the workspace UUID and both audit ARM IDs only for PoC001 explicit LA or PoC002.
It deliberately does **not** validate PoC001 Blob URL/container/writer at startup;
those failures belong to the best-effort history warning boundary. Backend typos
also belong to that boundary, not an implicit LA switch. It never reads checkout
dotenv or persona credential files.
The tenant ID is documented/format-validated metadata, **not a token-tenant
override**; administrators must verify actual VM/resource placement.

In non-VM legacy mode, dotenv is restricted to the PoC directory and no longer
overrides existing process values. Restart after editing settings rather than
expecting reruns to replace already loaded environment values.

## 6. Start and check private services

After the resource/identity/configuration gates pass:

```bash
sudo systemctl enable --now elv-poc001-agent.service elv-poc001-ui.service elv-poc002-ui.service
systemctl is-active elv-poc001-agent.service elv-poc001-ui.service elv-poc002-ui.service
curl --fail --silent --show-error http://127.0.0.1:9999/health
curl --fail --silent --show-error http://127.0.0.1:8501/_stcore/health
curl --fail --silent --show-error http://127.0.0.1:8502/_stcore/health
ss -ltn
```

All three listeners must be **127.0.0.1 only**. UI 001 starts after requesting
its agent; systemd ordering is not application readiness, so check health before
presenting. The UI can remain available for governance if the agent is restarting.
A successful health response proves process availability, not Azure connectivity.

Systemd supplies writable state/cache directories while the source is read-only
inside the service sandbox. PoC001 feedback goes to its private state directory;
retain it only as approved synthetic demonstration evidence. A2A tasks/contexts
remain in memory and are lost on restart. Streamlit sessions are also transient.

## 7. Presenter access (approved workstation)

Keep application execution on the VM. The following creates only SSH tunnels
on the workstation; substitute the approved SSH config alias with verified host
keys and the organization's authentication/Bastion/VPN configuration:

```text
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8501:127.0.0.1:8501 -L 127.0.0.1:8502:127.0.0.1:8502 <approved-vm-ssh-alias>
```

Open http://127.0.0.1:8501 and http://127.0.0.1:8502 in the workstation browser.
Use different local ports if necessary, keeping the VM destination ports above.
Do not forward the A2A agent publicly. Do not use SSH gateway ports, disable host
key checking or broaden the NSG to the internet. Bastion tunneling capability
depends on the organization's configured tier/client and must be verified.

## 8. Full acceptance and troubleshooting

Record outcomes on the VM; do not mark the migration complete without:

1. Both UIs fully functional: PoC001 baseline/candidate, approval, retrieval,
   citations, feedback and context refresh; PoC002 three locales, inheritance,
   glossary/disclosure handling, certification/drift and language checks.
2. Real RBAC outcomes: viewer cannot write; designer/market owner cannot publish;
   approver can publish; app cannot read drafts or write either store. The
   market-owner locale limitation remains visible, not falsely fixed.
3. PoC001 Blob mode works without a workspace: an approved app draft change and
  publication show before/after history and CSV; the separate reader can read
  but not upload, and neither identity has unrelated-container grants. Check
  warning behavior with mocks first, not by revoking customer roles. Legacy LA
  events (PoC002 and PoC001 opt-in) arrive under the intended identities/resources.
  Separate credential failure from denial and ingestion/role propagation.
4. No local secrets/operator CLI token dependency. Missing persona/audit-reader
  identities fail rather than borrowing another credential; a missing PoC001
  history writer warns without blocking configuration. Missing Search or Language is not
   accepted as a full-demo success merely because the UI degrades gracefully.
5. VM reboot (approved maintenance window): all services recover, all health
   checks pass, and presenters can reconnect. No unrelated service/data changed.

Use service status and journal logs for failures; review/redact before sharing:

```bash
sudo journalctl -u elv-poc001-agent -u elv-poc001-ui -u elv-poc002-ui --since '15 minutes ago' --no-pager
sudo systemctl reset-failed elv-poc001-agent elv-poc001-ui elv-poc002-ui
sudo systemctl restart elv-poc001-agent elv-poc001-ui elv-poc002-ui
```

- Permission denied before Python: verify source/venv traversal/read/execute,
  noexec mounts, environment-file ownership, and SELinux audit denials.
- Configuration error: fill the named nonsecret setting; units intentionally
  stop after repeated failures. Do not replace managed identities with secrets.
- 403: verify the selected identity and exact role scope; allow propagation.
- DNS/TLS: repair private DNS, routes, proxy bypass and approved CA trust.
- 429/model error: check deployment compatibility and token/request quotas.
- Search failure: verify actual index/alias schema and capacity; no forced API
  downgrade. The code's 2026-04-01 Search API is documented stable.
- PoC001 history unavailable/warning: inspect the backend, dedicated private
  container, separate writer/reader configuration and approved role/network path.
  Do not create a workspace or broaden grants as a fallback. Empty means no
  recorded events in the selection, not that no configuration changes occurred.
- Language unavailable/legacy LA empty: inspect the applicable access/diagnostic
  prerequisites; health checks alone cannot validate either service.

## 9. Update, rollback and stop

Before updating, record the source revision, resolved packages and approved
nonsecret config mapping; securely back up state/config as required. Stop the
three services, deliver the reviewed code, prepare/validate dependencies, rerun
the installer to refresh owned units, then restart and rehearse. No git pull,
pip upgrade or Azure mutation is hidden in application startup.

Rollback restores the prior reviewed source and its matching dependency set,
unit/config files and required state, then re-verifies startup. Do not overwrite
unrelated shared Azure objects to roll back this hosting package.

```bash
sudo systemctl disable --now elv-poc001-ui elv-poc001-agent elv-poc002-ui
```

For removal, an administrator reviews and removes **only** the three installed
units, their two environment files and, after retention approval, the two
service-owned state/cache directories/accounts; then reloads systemd. Do not
invoke either Azure teardown script. Revoke no shared identity without its
owner's approval. VM shutdown does not stop billing for existing managed Azure
services; confirm VM/RHEL licensing, service capacity and telemetry costs.

## External references

- [PowerShell on RHEL](https://learn.microsoft.com/en-us/powershell/scripting/install/install-rhel)
- [Azure CLI on Linux](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux)
- [Managed identity boundaries and tenant limitations](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/managed-identities-faq)
- [Azure Search service limits](https://learn.microsoft.com/en-us/azure/search/search-limits-quotas-capacity)