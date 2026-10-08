# Tasks: Profile-Specific Advisory Evaluation

Scope and acceptance: [spec.md](spec.md). Design: [plan.md](plan.md).

## Foundation

- [x] T001 Capture the accepted scope, contracts and test gates in this feature directory.
- [x] T002 Add failing policy/literal tests in PoC001 tests/test_evaluation.py, then implement strict pure policy validation and templates in evaluation.py.
- [x] T003 Add comparison-only evaluation opt-in and fixed-key policy load/create/update with ETag/history handling in rbac.py, config.py and change_history.py; extend mocked configuration tests.
- [x] T004 Add opt-in bounded evidence artifacts in experience_runtime.py and response A2A adapters; extend runtime and A2A contract tests.

## Evaluation and UI

- [x] T005 Implement bounded hybrid evaluation and evaluation.v1.prompty with exact output/reference validation; test all rule and incomplete/error states offline.
- [x] T006 Implement separate A2A evaluator server/agent/client with strict request contracts and offline HTTP+JSON tests.
- [x] T007 Add structured Rules authoring to config_editor.py/app.py and advisory findings after generation; extend AppTest for save/regenerate, independent profiles and failure retention.

## Delivery

- [x] T008 Extend deployment/windows/run.py with default-off evaluator component and loopback settings; extend launcher regressions without modifying external runtime JSON.
- [x] T009 Update PoC README, Windows runbook and white paper with demo, evidence limits, cost and future production gates/rewrites.
- [x] T010 Run full offline PoC/shared-hosting tests, editor checks, whitespace checks and mocked browser validation; record evidence and unverified live acceptance.

## Live Follow-Up

- [x] T011 Repair semantic judgment format/reference failures with strict structured output, known passage IDs and safe diagnostic stages; validate 323 offline tests and an explicitly approved evaluator-only replay of the failing response pair. No rule writes or new response generation.
- [x] T012 Diagnose intermittent model-request failure, add safe SDK error categories and bounded cooldown guidance without retries, and verify 325 offline tests plus two authorized successful replays. Record that the original HTTP/transport cause could not be recovered.

## Dependencies

T002 precedes T003/T004. T005 needs policy/evidence contracts; T006 needs T005.
T007 needs T003/T006. T008 follows service contracts. T009/T010 close implementation.
No live seed, inference, process restart, role/network change or automatic activation
is part of these tasks. Deployment acceptance is recorded separately, not marked as
verified by offline tests.