# Feature: Red Hat VM hosting for both PoCs

**Date:** 2026-09-08
**Status:** Implementation started; target VM verification pending

## Scope and user decisions

Host both existing Python demonstrations on an Azure Red Hat Enterprise Linux
VM. Preserve full demo functionality. Presenters may use an approved workstation
browser and SSH tunnel; application execution, dependency installation and tests
must happen on the VM, not on the workstation. Reuse existing Azure services;
approved PoC-specific additions may be made in a subsequent infrastructure step.

This slice implements hosting support and the credential selection required for
safe hosted execution. It does not provision Azure resources, assign roles,
reseed shared configuration, transfer old-tenant content or run teardown.

## User stories and acceptance scenarios

### US1 — Determine VM readiness (P1)

An operator can run a non-mutating readiness check on the target VM before
installing anything. It reports RHEL/Python/systemd/tool availability, disk,
SELinux/FIPS observations and port availability without printing credentials.
Missing optional Azure provisioning tools are warnings, not runtime blockers.

### US2 — Run both demonstrations headlessly (P1)

Two isolated Python environments host three non-root services: PoC 001 UI on
127.0.0.1:8501, its A2A agent on 127.0.0.1:9999, and PoC 002 UI on
127.0.0.1:8502. Services survive logout and can restart after reboot. Runtime
writes go to designated state directories, not the source checkout. SSH tunnels
terminate on workstation loopback; application ports are not publicly exposed.

### US3 — Preserve governance without local secrets (P1)

Azure VM mode uses distinct explicitly selected managed identities for every
existing persona and a separate audit identity. Missing, malformed or duplicate
identity mappings fail closed. VM mode never reads repository credential files
or falls back to Azure CLI/environment client secrets. Operator-provided service
configuration cannot be replaced by an old dotenv file. Resource-context audit
queries restrict the requested logs to the two configured App Configuration
resources; permissions must also be scoped by the administrator.

### US4 — Operate and validate remotely (P2)

A runbook describes preparation, configuration, permissions, startup, tunnels,
health checks, tests, reboot verification, update/rollback and local-service-only
removal. Installation is opt-in, does not overwrite existing environment files,
does not start services before configuration, and performs no Azure mutation.

## Constraints and security boundary

- The VM is a trusted presenter environment. Its users/code can access attached
  identities; OS users and the persona selector are not authorization boundaries.
- Identities and target resources must support direct same-tenant access. Actual
  tenant placement, assignments, service capacity and connectivity are unverified.
- No passwords, tokens, client secrets or private keys belong in chat or source.
- Do not run existing provisioning/teardown scripts against shared resources.
- No public UI/API, GUI desktop, GPU, containers, HA or full Bash rewrite required.
- Supported Python/RHEL and package-install permission are deployment gates.
- Source/static checks may run in the editor; PoCs and executable tests run only
  on the approved VM. No VM access has yet been provided.

## Success criteria

All three services start privately using ready existing Azure resources, the
complete demonstrations work, the existing and new remote tests pass, expected
Azure RBAC denials remain real, and another operator can reproduce startup and
recovery. Source implementation alone is not evidence of VM compatibility or
successful new-tenant migration.