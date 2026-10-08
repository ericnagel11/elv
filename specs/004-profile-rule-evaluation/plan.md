# Implementation Plan: Profile-Specific Advisory Evaluation

**Date**: 2026-10-07 | **Spec**: [spec.md](spec.md) | **Branch**: existing `main`

## Summary

Add independent profile rule policies and a read-only A2A evaluator after comparison
generation. Preserve generated text and all current generation safeguards. Re-running
the prompt is the evaluation refresh workflow. Reuse existing SDKs; no new cloud service.

## Technical Context

- Python 3.10+ (target Windows venv 3.14), Streamlit, Azure App Configuration SDK,
  Azure OpenAI, existing A2A 1.0 HTTP+JSON/Starlette and Prompty/Jinja rendering.
- Policies in the existing App Configuration store; opt-in existing Blob config
  history for rule mutations only. Results/evidence remain in memory.
- unittest, httpx.ASGITransport and existing Streamlit AppTest network-isolation harness.
- Existing UI/agent ports 8501/9999; proposed evaluator loopback port 10000.
- Strict default-off `ELV_ENABLE_EVALUATION`; one judge call at most per comparison,
  finite deadline, no retries or repair calls. Never fetch source URLs during judging.

## Constitution Check

Pre/post-design: PASS with existing documented VM demo limitations retained. Reuse
GA Azure services, approved identity and installed dependencies. Custom validation,
evidence correlation and evaluator adapters are needed for the profile-specific
contract; no general-purpose evaluation platform or new orchestration framework.
The third local process demonstrates an independently callable evaluator, not
independent identity isolation. Human review, bounded costs and incomplete evidence
are explicit. Production gates/retention/security are not implied by this demo.

## Design and Contracts

### Rule Policy

One fixed key `rules:policy`, labeled `baseline` or `candidate` (never default label).
JSON: `schema_version: 1`, `enabled: bool`, `rules: list`. Each rule has `id`, `title`,
`type`, `enabled`, `severity` (high/medium/low), `criteria`, and `parameters`.
Types: `literal_phrase`, `absolute_claim`, `unsupported_assurance`, `fact_preservation`.
Literal parameters: bounded `terms`, `match` (phrase/substring), `case_sensitive`.
Preservation parameters: `compare_baseline` boolean; other semantic types use `{}`.
Reject unknown/duplicate JSON fields, duplicate IDs, invalid types and Unicode;
maximum 10 rules and 8192 UTF-8 bytes. Rules use literal matching, never user regex.
Revision: exact ETag plus canonical SHA-256 policy hash.

Dedicated config helpers enforce the fixed key/labels and existing edit opt-in.
First Save uses atomic create-only; updates use loaded ETags/IfNotModified. No-op
does not write. History failures never reverse or retry a config save. Do not
broaden experience/knowledge/full-demo mutation allowlists.

### Evidence and Evaluation

An explicitly requested, feature-gated, versioned A2A evidence artifact carries
profile, response task/context IDs, text/hash, question hash, generation revision,
prompt/grounding/finish/citation status, scope revision and the exact bounded source
excerpts with local IDs, hashes and truncation flags. No system prompts, filters,
credentials or arbitrary source fetches. Existing 20-source/2500-character bounds
apply. Oversized/incomplete snapshots cannot silently receive a clean evaluation.

The evaluator accepts one versioned structured comparison with both snapshots,
validates it, and reads each profile policy once per call. Run literal checks first;
batch semantic checks into one fixed versioned judge prompt with a strict Azure
OpenAI JSON response schema. Restrict the model to requested profile/rule IDs and
known passage IDs; locally resolve those IDs into exact original quotation text.
Passages are contiguous slices of at most 500 characters, preserving all supplied
text. This is reference selection within existing excerpts, not new retrieval.
Only requested profiles and an eligible baseline reference enter the judge input.
Validate every active rule's response, profile, quotes and references. Treat all
request content as data, not instructions, and return concise reasons, not hidden
reasoning. Failed judgments expose fixed diagnostic stage codes, never raw model
content or provider exception text. Structured-output model/API support is required;
unsupported requests remain errors rather than falling back to prompt-only JSON.

Rule outcomes: `finding`, `no_finding`, `not_applicable`, `not_verifiable`, `error`.
Policy states: `complete`, `partial`, `unavailable`, `not_configured`, `disabled`,
`no_active_rules`. Severity comes from stored policy. Include used rule revision,
response correlation, evaluator prompt/deployment, timestamp, token usage and latency.
No claims of member-specific determination or truth based only on citation markers.
Baseline-backed preservation requires compatible source scope and actual source
support; available evidence is not proof of complete retrieval.

### UI and Lifecycle

Configuration > Rules is independent of RAG. Saves clear old comparison state;
direct Azure rule edits are observed by the next evaluation without generation
context refresh. Store answers before evaluation and keep them on evaluation failure.
Only Generate initiates evaluation; tabs, feedback and rerenders must not call it.
Show findings/coverage under each response and evaluation cost separately.

## Implementation Surfaces

New focused modules: `evaluation.py`, `evaluation_agent.py`, `evaluation_client.py`,
`evaluation_server.py`, one evaluation Prompty asset and `tests/test_evaluation.py`.
Reuse `config.py`, `config_editor.py`, `rbac.py`, `change_history.py`, `app.py`,
`experience_runtime.py`, response A2A adapters, `prompt.py`, Windows launcher and
existing contract/config/AppTest suites. Leave PoC002 and generation prompt bodies alone.

## Validation and Rollout

Follow [tasks.md](tasks.md) with focused executable validation after each slice.
Run all PoC unittest tests and shared hosting tests offline. Use local mocks for
UI/semantic cases; do not claim those prove judge accuracy. Live acceptance and
external runtime opt-in require an approved rollout; do not seed policies or make
billable model calls automatically. Document commands in the Windows runbook.

No extension hooks were present during setup. Keep running processes and external
runtime configuration unchanged during implementation. No new branch or commit.