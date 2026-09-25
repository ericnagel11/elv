# Tasks: Red Hat VM hosting

This is a dated work record, not one deployment recipe. Later Windows milestones
do not complete the earlier Red Hat/full-governance gates. The current status is
recorded in [validation.md](validation.md#history-activation-and-user-acceptance-2026-09-23).
The 2026-09-23 implementation scope is documentation only; open operational tasks
below are not authorization to change services, permissions or application code.

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

## Follow-up — Windows comparison milestone (2026-09-16)

User-approved scope: PoC001, one existing managed identity, GPT-4o, localhost
viewing first. The full Red Hat/multi-persona acceptance gates above are not
replaced or marked complete by this reduced Windows milestone.

- [X] T017 Add opt-in runtime-only credentials and backend restrictions for
  configuration writes, permission probes, draft/knowledge reads and audit.
- [X] T018 Add GPT-4o request formatting without reasoning-only parameters;
  preserve default asset-driven model requests and test both contracts.
- [X] T019 Render comparison-only UI with generation, metrics, provenance,
  feedback and refresh; test that disabled tab bodies do not execute.
- [X] T020 Add Windows foreground launcher, external JSON validation, fixed
  loopback listeners and preserved proxy/CA configuration; document operations.
- [X] T021 Complete integrated VM dependency, PoC and shared-hosting regression
  checks; record resolved versions and editor/diff validation.
- [X] T022 Prepare protected local runtime/state, validate settings, start both
  localhost components and verify process health/listeners on Windows.
- [X] T023 Obtain explicit approval and initialize the 12 synthetic profile
  settings using the configured runtime identity; verify create/read access
  on the selected store. No automatic startup writes or role changes.
- [ ] T024 Verify real GPT-4o baseline/candidate responses and configuration
  refresh against populated Azure profiles; retain synthetic acceptance evidence.
  User confirmed two successful comparison responses on 2026-09-16; refresh
  after a deliberate approved profile change remains unverified.
- [ ] T025 Separately approve/design private-IP HTTPS and persistent Windows
  hosting, then verify private viewer access, WebSockets and reboot recovery.
  Deferred by the customer on 2026-09-17. Retain the Windows runbook handoff for
  future use; current users sign into the VM and use localhost. No network changes.
- [X] T026 Add a separate preview-first, create-only configuration initializer;
  test identity selection, approval gates, collisions, repeated runs and partial
  failure without overwrites or rollback. Document preview and approved apply.

## Follow-up — Local live configuration editor (2026-09-17)

- [X] T027 Add explicitly enabled, version-conditional editing of existing
  baseline/candidate experience settings with the same runtime managed identity;
  preserve disabled broad writes, draft publishing, audit and other personas.
- [X] T028 Add the Configuration tab with load/save, bounded prompt choices,
  conflict feedback and cleared comparison state after a successful save; test
  backend, UI and runtime JSON opt-in behavior without Azure writes.
- [X] T029 Enable editing in the local runtime configuration, restart the UI,
  verify the tab/real setting load and record integrated regression results.
- [ ] T030 Verify a user-chosen live save and subsequent response refresh. Do
  not change customer configuration or spend inference quota just to deploy UI.

## Follow-up — Existing-index RAG (2026-09-18)

- [X] T031 Confirm the selected existing index and content-use approval; inspect
  supplied fields and verify text/metadata/filter capabilities with bounded
  read-only queries, without schema changes or expanded permissions.
- [X] T032 Add opt-in approved-index RAG and configurable field mappings, exact
  filters, bounded excerpts and no-model behavior for empty results; preserve
  the original comparison and full-governance contracts with offline tests.
- [X] T033 Add the grounding toggle, source citations and Knowledge configuration
  editor with typed controls and version-safe saves; validate UI/context behavior.
- [X] T034 Extend the existing initializer with a knowledge-only preview/apply
  path; obtain explicit approval and create/read back the 32 knowledge settings
  without modifying experience values or the Search index.
- [X] T035 Restart both local components and run the approved live GPT-4o RAG
  comparison; verify two responses with source citations and record the evidence.
- [X] T036 Finalize the existing-index configuration/filter runbook and final
  deployment diagnostics. Vector/hybrid/semantic implementation is outside this
  initial keyword-RAG milestone.

## Follow-up — VM and healthcare merge repair (2026-09-22)

- [X] T037 Restore configuration imports, conflict exceptions, comparison write
  guards and mutation notices while preserving full-demo history behavior.
- [X] T038 Reconcile Search normalization and mappings; preserve blank filters,
  healthcare prompts and both grounding modes. Restore lost runtime coverage.
- [X] T039 Integrate the shared Search form into the VM live editor with approved
  indexes, ETags, blank-filter acknowledgment and honest partial-save outcomes.
- [X] T040 Complete merged offline suites, shared deployment contracts, runtime
  validation and handoff documentation without live Azure changes or restarts.
- [ ] T041 User stops both processes, installs matching requirements in the
  existing venv, restarts via the Windows launcher and verifies healthcare
  comparisons and configuration editing locally. No automatic reseeding.
  Dependency installation/restart and 258 offline tests completed on 2026-09-22;
  user response/filter/citation feedback is being addressed below.

## Follow-up — Search diagnostics and inline citations (2026-09-22)

- [X] T042 Surface sanitized Search query rejections as task errors, not agent
  outages; remove the incompatible sample filter hint from the VM form.
- [X] T043 Validate inline marker presence/source numbers, withhold invalidly
  cited answers without fabricated citations or automatic retry, and propagate
  applied citation style/status to the UI. Label retrieved sources explicitly.
- [X] T044 Deploy the verified local diagnostic/citation updates and record
  health checks; leave saved Azure configuration and model testing to the user.

## Follow-up — VM Blob configuration history (2026-09-22)

- [X] T045 Add explicit default-off VM history using the approved runtime
  identity, preserving full-mode credential and edit boundaries; wire versioned
  live writes and grouped save warnings to the existing best-effort recorder.
- [X] T046 Add an opt-in Change history view and preserve history warnings across
  single-key saves; test metadata, failures, no-ops, grouping and safe reads offline.
- [X] T047 Stage the approved target with logging disabled and document the
  container/access/activation handoff; complete regression and local checks.
- [X] T048 Create/confirm the private history container, enable history and verify
  a changed configuration save/readback. The user explicitly authorized script
  apply on 2026-09-22; it created the private container and enabled the flag,
  followed by a UI restart. Save/readback was user-confirmed on 2026-09-23.
  This does not verify exact role scope, retention or live warning paths; see T051.
- [X] T049 Add a separate preview-first history setup script that creates or
  verifies the private container, then enables only the local history flag.
  Preserve existing contents/policies and stop on public targets or denied access.
- [X] T050 Verify script regressions, local preview and activation instructions.
  Setup requires explicit operator authorization, never application startup.
- [ ] T051 Confirm effective least-privilege role scope, retention ownership and
  live history warning/failure acceptance without changing shared permissions to
  induce failures. This retains the unverified parts of the original T048.

## Follow-up: documentation accuracy and architecture (2026-09-23)

- [X] T052 Correct current-state evidence, governance, refresh, retrieval and
  PoC002 status in the whitepaper and linked runbooks; retain historical evidence.
- [X] T053 Document proposed bounded A2A coordination for compound read-only
  healthcare guidance, including typed evidence, identity and failure boundaries.
- [X] T054 Document large-corpus metadata assessment, field contracts, query
  stages, access alternatives, lifecycle and evaluation without index changes.
- [X] T055 Extend generic architecture review criteria and document the current
  PoC exceptions without weakening normative requirements or inventing approval.
- [X] T056 Validate documentation links, diagrams, consistency and Markdown-only
  change scope. No deployment commands, model calls or application tests required.