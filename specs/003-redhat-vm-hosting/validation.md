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