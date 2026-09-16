# App Configuration: one-service access check

**Status (2026-09-14):** Customer confirms admin access to the same-tenant Azure
Windows VM, the supplied user-assigned identity attached, and Azure CLI installed.
The customer reran the corrected Windows probe and supplied `READ_SUCCEEDED`.
This confirms explicit managed-identity sign-in and a data-plane key-metadata
list request to the selected App Configuration store from that VM. App
Configuration Data Owner is reportedly assigned, but write/update/delete rights,
store creation, other Azure services and full PoC readiness remain untested.
The probe made no configuration changes. This assistant has made no Azure
requests or configuration writes.

The Windows probe does not require Bash, WSL, either PoC, or the Red Hat systemd
installer. Full Windows application deployment remains separate work, not
implicitly complete. Execute Azure checks on the customer VM, not the separate
workstation hosting this checkout.

This is independent of starting the PoCs, configuring other Azure services or
provisioning infrastructure. The existing store need not be recreated. The user
reports that it is empty and dedicated to the PoCs; the probe does not inventory
its contents or infer emptiness from the portal Overview.

## Permissions are not an execution location

- App Configuration Data Owner on the target store permits read/create/update/
  delete of its data. It does not create stores or assign roles. No additional
  Data Reader assignment is required for the same identity at that scope.
- Attaching a managed identity to App Configuration lets that service use the
  identity for its dependencies. It does not create a shell for our test and
  does not give a workstation or ordinary Cloud Shell session that identity.
- Execute the appropriate probe only on an approved Azure Windows or Linux host with the
  selected user-assigned managed identity attached and an accessible identity
  endpoint. Do not attach a broadly privileged shared identity to new compute
  without its owner's approval. An administrator may run the probe for the user.
- The host must reach the store's HTTPS data endpoint through the approved
  network/private DNS route. Do not open public access or disable TLS checking.
- The host/identity must support access in the store's tenant. No tenant transfer
  or cross-tenant federation is performed by this probe.
- A service principal in an approved pipeline is an alternative, but is not a
  fallback in this managed-identity probe. Agree its separate secure workflow
  rather than provide a client secret to the script or chat.

## Administrator handoff

Confirm these nonsecret facts before running:

1. The Data Owner assignment is for the intended managed identity and covers the
   actual App Configuration store (prefer store scope, not the entire subscription).
2. Identity **client ID** for login; principal/object ID is used separately when
   administrators assign roles. A client ID is not a password or token.
3. Approved execution host, existing identity attachment and authorized operator.
4. Azure CLI installed, with managed-identity client-ID login and App Configuration
   commands supported; approved CA/proxy configuration and reachable data endpoint.

### Windows VM team checklist

- Confirm the Windows VM's name/resource ID and that it is approved for this
  identity and its existing permissions. All code/users on a VM can potentially
  use its attached identities; a separate Windows account is not MI isolation.
- An authorized administrator opens the **Windows VM -> Identity -> User
  assigned -> Add**, selects the approved existing identity and saves. Preserve
  its existing App Configuration and other associations; attaching to the VM is
  not a transfer. Do not enable a new system-assigned identity as a substitute.
- Attaching requires VM write permission and permission to assign the UAMI
  (for example, Managed Identity Operator on that identity). This is an
  administrator task; the PoC runtime does not need those management permissions.
- Verify the identity's already-granted **App Configuration Data Owner** applies
  to this store. Do not add a redundant Data Reader or broaden to subscription
  Owner. Data Owner includes read but does not itself allow identity attachment.
- Ensure the Windows VM can reach IMDS and the App Configuration endpoint using
  approved private DNS/HTTPS/proxy/CA settings. Leave public access unchanged.
- Provide an approved RDP/Bastion route and named Windows login, or run the
  standalone test on the user's behalf. Sharing the VM password, token or a
  private key in chat is not required. RDP access, permission to install Azure
  CLI and Azure managed-identity data access are distinct approvals.
- Install approved Azure CLI if needed, open a new terminal to pick up PATH,
  and use Windows PowerShell 5.1 or PowerShell 7 on the VM. Follow existing
  execution/signing policy; do not disable policy or run with an execution-policy
  bypass. No local administrator elevation is required by the probe itself.

Allow role propagation before interpreting an initial denial. App Configuration
documentation advises allowing up to 15 minutes after role assignment; other
identity/cache changes can require longer. Prefer re-running this bounded check
after the administrator confirms readiness, rather than broadening permissions.

## Read-only probe

Both probes take only nonsecret connection metadata. They establish their own
explicit managed-identity sign-in; a prior user login is neither required nor
used. Deliver the reviewed script to the approved host before running it.

### Windows VM (current target)

[check-access.ps1](check-access.ps1) uses PowerShell 5.1/7 and the installed Azure
CLI. Substitute the store endpoint and UAMI **client ID** provided to the team:

```powershell
& .\deployment\appconfig\check-access.ps1 -Endpoint 'https://YOUR-STORE.azconfig.io' -ClientId 'YOUR-UAMI-CLIENT-UUID' -ApprovedAzureHost
```

The acknowledgement switch means the operator has confirmed the execution host
is authorized Azure compute with this identity attached. It is not proof of
attachment or a permission grant. Do not run the probe on a workstation merely
because it also runs Windows. Invoke normally with `&`, not by dot-sourcing.

Open PowerShell first and invoke the script from that existing window. Launching
with **Run with PowerShell** can close the window before the summary is read;
dot-sourcing can let the script's `exit` close the caller's shell. Results are
console-only, not a permanent log. All three arguments above are needed; launching
the script without them exits before any access check.

Before Azure CLI writes any credential cache, the script restricts a fresh
temporary directory to the current Windows identity and SYSTEM. It stops if
this cannot be established; VM administrators still control the machine. Its
`finally` block restores the caller's environment settings and removes the
temporary directory. A cleanup failure is separately reported with exit 5.
It does not alter the operator's existing Azure CLI cache or sign-in.

### Linux alternative

[check-access.sh](check-access.sh) takes a store endpoint and user-assigned
managed-identity client UUID. Run on the approved Azure Linux host:

```bash
bash deployment/appconfig/check-access.sh https://YOUR-STORE.azconfig.io YOUR-UAMI-CLIENT-UUID
```

Both probes:

- Uses a private temporary Azure CLI configuration directory and explicitly signs
  in as the supplied identity; it cannot reuse an operator's cached user login.
- Uses only Entra authentication, never access keys or connection strings.
- Makes a data-plane list request for at most one item's key metadata. It prints
  neither names nor values and does not resolve Key Vault or snapshot references.
- Do not import/run either PoC or require PoC dependencies; Azure CLI and the
  selected shell are sufficient.
- Does not create, modify, delete or seed configuration, create resources or
  change RBAC. Azure may record authentication and request audit events.
- Preserves the parent shell's sign-in/configuration. Temporary CLI cache/error
  files are private and removed on normal exit or handled interruption; cleanup
  cannot be guaranteed after a host crash or uncatchable termination. Do not copy
  these files. Honor the organization's token-cache handling policy.
- Emits fixed diagnostic categories rather than raw CLI errors. For deeper
  troubleshooting the authorized host administrator should inspect diagnostics
  through approved secure tooling; do not share full token/configuration dumps.

Each preserves inherited CA/proxy settings, appending IMDS/loopback proxy bypasses.
Each requires the standard commercial Azure endpoint even with Private Link; DNS
on the approved host should resolve it appropriately. Neither disables TLS,
install software, log in interactively or solicit credentials.

| Exit | Interpretation |
|---|---|
| 0 | Managed-identity data read succeeded, even if the store is empty. |
| 2 | Invalid input, wrong host platform or missing tooling. |
| 3 | Explicit managed-identity login failed; no store request was made. |
| 4 | Store read failed. Check the reported category and actual platform diagnostics. |
| 5 | Windows temporary-cache cleanup failed; secure administrator cleanup is needed even if the read succeeded. |

A 403 can reflect role scope/propagation or network restrictions; it is not
automatic evidence that Data Owner is missing. Timeout/TLS/DNS failures are not
fixed by adding roles. Success proves neither write permission nor endpoint
reachability from a different host, including the eventual PoC VM.

## After read access succeeds

1. Obtain explicit approval for a small write/update/readback test on a new,
   uniquely named synthetic key, with collision protection and agreed cleanup.
   No such write/delete test is included in the current probe.
2. Confirm which PoC owns this initial store before seeding. Both existing seed
   scripts write overlapping baseline keys; do not run both unchanged here.
3. Separately plan live/draft store isolation and distinct runtime/designer/
   approver roles. One newly assigned Data Owner identity does not implement the
   full governance demonstration or make all personas interchangeable.

## Validation status

The implementation is intentionally runnable without either PoC installed.
Static checks passed on 2026-09-11: Bash syntax-only parsing, LF line endings,
Git diff whitespace, local documentation link targets, and a source check for
unexpected Azure mutation/credential-list commands. Editor diagnostics reported
no errors. The customer's initial Windows login failure report was inconclusive
because of the native exit-code shadowing bug, which was reproduced locally and
corrected. On 2026-09-14, the customer subsequently supplied `READ_SUCCEEDED` from
the corrected probe on the approved VM. This is customer-run evidence of explicit
identity login and store read access, not a write test or full deployment test.

[tests/test-check-access.ps1](tests/test-check-access.ps1) exercises the production
native-command wrapper with a local batch fixture. It checks success, failure,
success after failure, parent-scope shadowing, launch failure, output suppression
and error-preference restoration. It neither runs the full probe nor invokes
Azure CLI or IMDS, and requires no Azure identity or Pester installation:

```powershell
& .\deployment\appconfig\tests\test-check-access.ps1
```

On 2026-09-14, all seven offline assertions passed in Windows PowerShell 5.1,
including the regression for the false login failure. Editor diagnostics reported
no errors. These local checks are separate from the customer-run Azure read
success above. PowerShell 7 execution remains unverified; the customer VM's exact
PowerShell version has not been recorded.

Reference: [App Configuration data roles](https://learn.microsoft.com/en-us/azure/azure-app-configuration/concept-enable-rbac)
and [managed-identity Azure CLI sign-in](https://learn.microsoft.com/en-us/cli/azure/authenticate-azure-cli-managed-identity).