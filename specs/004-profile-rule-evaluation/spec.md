# Feature Specification: Profile-Specific Advisory Evaluation

**Created**: 2026-10-07 | **Status**: Accepted for implementation
**Working branch**: existing `main`; no feature branch requested.

## User Scenarios & Testing

### US1 - Add a Profile Rule and Run Again (P1)

A presenter generates baseline/candidate answers, adds a baseline rule in
Configuration > Rules, saves to App Configuration, and runs the same prompt again.
Only baseline's evaluation policy changes. No restart or old-answer replay is needed.

**Independent test**: mocked UI/configuration workflow, including direct Azure edits
between comparisons and an unchanged candidate policy.

### US2 - Understand Risky Wording (P1)

The presenter sees advisory severity, offending wording, explanation, supporting
excerpts and evaluation coverage alongside the original response. Checks include
absolute coverage/cost assurances, unsupported negative prior-authorization/referral
assertions, and lost cost-share conditions, limits and exclusions.

**Independent test**: synthetic fixtures include '100% covered at no cost', 'No prior
authorization is needed', and '$50 after deductible' becoming '$50', plus negated and
conditional safe wording. Baseline is not automatically authoritative.

### US3 - Recognize Incomplete Evaluation (P1)

Missing/disabled/empty rules, invalid policies, absent/truncated evidence and evaluator
failures are distinguishable from completed checks with no findings. Responses remain
visible when evaluation fails. Ordinary UI reruns never incur another evaluation.

## Requirements

- **FR-001**: Independently store versioned `rules:policy` JSON under baseline/candidate
  labels; no null-label fallback, cross-profile inheritance or caller-supplied policy.
- **FR-002**: Provide structured add/edit/disable/remove controls, explicit saves,
  create-only first writes, ETag updates, no-op handling and best-effort config history.
- **FR-003**: Fetch current policies on every newly requested comparison evaluation,
  independently of pinned generation contexts. Report the revisions actually used.
- **FR-004**: Use literal phrase checks and a separate localhost A2A semantic evaluator
  using the existing approved model/identity. Bound inputs, output, time and model calls.
- **FR-005**: Evaluate exact bounded generation excerpts, not citation metadata alone.
  Evidence export is opt-in; existing A2A clients do not receive new source bodies.
- **FR-006**: Validate all judge statuses, rule/profile IDs, quotations and evidence
  references. Display uncertainty; never equate missing evidence with a pass.
- **FR-007**: Preserve answer text and current prompt/citation/access safeguards.
  No new suppression, automatic rewriting, promotion gate or approval workflow.
- **FR-008**: Keep evidence and findings in memory, not configuration history, feedback
  CSV or a new store. Rule changes may use the existing private configuration history.
- **FR-009**: Default evaluation off; preserve PoC002 and full-governance behavior.
  No automatic cloud provisioning, seeding, networking, role or runtime JSON changes.
- **FR-010**: Document demo steps, costs, shared-identity limitations, evidence gaps,
  future production gates and a later human-reviewed rewrite milestone.

## Success Criteria

- The add-rule/save/regenerate workflow demonstrably uses a new baseline policy
  revision without changing candidate's policy or restarting services.
- Deterministic tests cover all policy/error states and each illustrative scenario;
  mocked model results establish plumbing, not semantic model accuracy.
- Evaluation outages leave both answers visible with explicit unavailable coverage.
- Existing offline tests and focused new contracts pass without Azure calls.
- Any live model-quality or deployment acceptance not performed is explicitly recorded.

## Assumptions and Limits

Synthetic questions and approved excerpts only. Rules change evaluation, not model
generation; another generation can produce different wording. The PoC has no
member-specific eligibility/authorization determination service. It cannot discover
exclusions never retrieved, or prove complete coverage from truncated sources.
Mandatory shared production safety rules, retrieval-completeness controls, approval
and Block/Warn gates belong in the white paper's production roadmap.