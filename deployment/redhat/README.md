# Red Hat Azure VM hosting — both PoCs

**Status:** Source implementation; target VM execution and Azure validation are
pending. This is a trusted presenter deployment, not a production multi-user app.

Both UIs are headless web applications. No server desktop or GPU is needed.
Application execution, package installation and tests below happen **on the VM**.
Only the browser/SSH client runs on the approved workstation. The Red Hat-only
effort estimate is 2–3 engineering days (allow 4), assuming Azure prerequisites
are ready. Tenant/resource migration and substantial network remediation are
separate work.

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
- VM DNS/routing/HTTPS to App Configuration, OpenAI, Search, Language and Monitor;
  private endpoint DNS/peering as required. Bootstrap also needs Blob access.
- IMDS access at 169.254.169.254, bypassing proxies. Merge the examples' NO_PROXY
  values with approved existing bypasses; do not replace required enterprise CA
  or proxy configuration. Browser-to-VM connectivity does not prove Azure access.
- **Search indexer-to-Blob** identity/network access independently of VM egress.
- RHEL package/FIPS/SELinux compatibility. Resolve denials with the administrator,
  rather than disable enforcement. Source execution from /opt/elv must be allowed.

## 2. Ready Azure resources and permissions (administrator)

Supply an approved mapping before starting services. Runtime environment files
are deliberately incomplete templates and fail validation until filled in.

| Dependency | Required mapping / preparation |
|---|---|
| App Configuration | Distinct live/draft stores for each PoC, endpoints **and** full ARM IDs. Do not share unchanged stores between PoCs: baseline keys collide. |
| OpenAI | Existing compatible Azure OpenAI endpoint, deployment name, model/API version and sufficient quota. Both PoCs may share one deployment. A Foundry project URL is not a substitute for the account endpoint used by this code. |
| Search | Existing suitable service, correct schemas/content and configured aliases. Four initial indexes combined (1 + 3), plus version/alias headroom; one Free service is insufficient. Preserve each language's analyzer. |
| Blob | Approved PoC-only containers and working indexers; prefer Search-to-Blob managed identity on a suitable tier. No storage key fallback is implemented by hosting. |
| Language | PoC002 custom-subdomain endpoint supporting Entra authentication and language detection. Required for the selected full demo. |
| Audit | Workspace customer UUID, resource logs AACAudit/AACHttpRequest enabled for each store, resource-context query authorization and ingestion verified. |
| Identity | Distinct managed-identity **client IDs**, not principal/object IDs, attached to the target-tenant VM; full resource IDs/object IDs retained separately for administrators. |

Create/reuse four persona identities for 001 and five for 002, **plus a dedicated
audit identity for each PoC**. Do not grant one identity all personas' rights.
No identity creation or role-assignment commands are run by the installer.

| Identity | Scope and minimum intended permissions |
|---|---|
| Viewer | App Configuration Data Reader on that PoC's live and draft stores |
| Designer | Data Reader on live; Data Owner on draft |
| Market owner (002) | Same as designer; Azure still does not enforce locale-specific labels |
| Approver | Data Owner on the two PoC-only stores |
| App | Data Reader on live only; Cognitive Services OpenAI User on approved OpenAI resource; Cognitive Services Language Reader on Language for 002 |
| Querying personas | Search Index Data Reader for approved PoC indexes, verifying alias access and role scope; never broad access to unrelated confidential content |
| Audit | Resource-context log-query rights only on the two approved stores, with the workspace access-control mode configured to support them |
| Search indexer identity | Storage Blob Data Reader on assigned PoC containers |

Use direct resource assignments where appropriate and allow propagation. Do not
give runtime identities provisioning rights. An administrator can perform scoped
setup separately using their approved MFA workflow. Direct VM managed-identity
access assumes the resource tenant is compatible; changing AZURE_TENANT_ID does
not move a VM identity into another tenant.

VM audit calls use resource-context queries, not broad workspace queries. If the
existing workspace/table setup does not permit that mode, stop and arrange an
approved logging design. Do not grant workspace-wide read merely to suppress a
403. An empty audit tab is not proof diagnostics are working; trigger an approved
PoC write/denial and confirm its arrival after ingestion delay.

This slice expects the appropriate demo configuration, aliases, documents and
diagnostics to **already exist**. It does not decide whether to reseed repository
samples or transfer custom old-tenant state. Confirm that decision separately.

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
all required endpoints, identity IDs, resource IDs and existing deployment name.
Keep placeholder values out of the live configuration.

The launcher forces azure-vm mode regardless of environment-file settings,
validates the full-demo settings without token requests, and uses only explicit
managed identities. It never reads checkout dotenv or persona credential files.
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
3. Audit events arrive under the correct identities/resources; audit identity
   cannot read unrelated resources. Separate a 401/credential failure from the
   intentional 403/authorization denials and from ingestion/role propagation.
4. No local secrets/operator CLI token dependency. A missing identity fails
   rather than borrowing another credential. Missing Search or Language is not
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
- Language unavailable/audit empty: inspect their access/diagnostic prerequisites;
  health checks alone cannot validate either service.

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