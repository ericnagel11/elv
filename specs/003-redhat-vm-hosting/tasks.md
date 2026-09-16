# Tasks: Red Hat VM hosting

## Phase 1 — Source implementation

- [X] T001 [US3] Add shared tests in deployment/redhat/tests for both hosting
  helpers, credential selection, audit scoping and launch/service contracts.
- [X] T002 [US3] Implement hosting.py in each PoC; wire entrypoints and rbac.py
  to authoritative VM configuration and fail-closed managed identities.
- [X] T003 [US3] Wire prompt.py, audit.py and PoC002 language.py to explicit
  service identities; use resource-context audit queries in VM mode.
- [X] T004 [US2] Move PoC001 feedback writes to configurable persistent state.
- [X] T005 [US1] Add deployment/redhat/preflight.py with read-only VM checks.
- [X] T006 [US2] Add environment preparation, guarded service installer, private
  launcher, three systemd units and nonsecret configuration examples.
- [X] T007 [US4] Add runbook, README links/warnings, ignore rules and LF policy.
- [X] T008 [US4] Review source, Bash syntax, diff and editor diagnostics.

Static results are recorded in [validation.md](validation.md). Python imports,
Python syntax compilation, executable tests and service execution were not run
locally; only Bash syntax parsing and source/document consistency were checked.

T001 precedes implementation; executing the tests is deliberately deferred to
Phase 2 because local PoC/test execution is prohibited. T002 precedes T003.
T005 and T006 may be authored after T001 independently of Azure provisioning.

## Phase 2 — On the approved Red Hat VM (blocked: connection route and permissions pending)

RHEL 8.10, 2 vCPU/4 GiB, running status and private networking were supplied on
2026-09-08; see [validation.md](validation.md). These are inventory facts, not
evidence of executed readiness checks. T009 remains open until VM inspection.

  sources, private access, trusted VM tenancy and Azure network/identity mapping.
  PoC001 tests, bash syntax checks and systemd-analyze verify on the VM.
  allowed/denied operations and resource-scoped audit access against real Azure.
  reboot and repeatable operating instructions; record evidence and versions.

## Follow-up — Windows App Configuration access check (2026-09-11)

The team has set up a Windows VM, but the user cannot access it yet. This is
limited to a standalone App Configuration probe; the Red Hat service deployment
is not silently converted or reported complete. Customer reports Data Owner
was granted; scope/effective permission and compute attachment remain unverified.

- [X] T013 Add Windows PowerShell read-only managed-identity probe alongside
  deployment/appconfig/check-access.sh; isolate its credential cache and restore
  the caller's environment; disclose no configuration values or tokens.
- [X] T014 Document Windows invocation, platform-team identity attachment/access
  handoff and scoped read/write distinctions in deployment/appconfig/README.md.
- [ ] T015 Validate PowerShell parsing and static safety contracts without
  executing the probe, logging in, or running either PoC locally.
- [ ] T016 On approved Windows VM, verify ACL/cache cleanup, correct managed
  identity login and App Configuration read, including an empty store; retain
  write/update tests and seeding as separate approved steps.

Do not mark T009–T012 complete on source review alone. This feature does not
create/seed/delete Azure resources; their readiness is an external prerequisite.