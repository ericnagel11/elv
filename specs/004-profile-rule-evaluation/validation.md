# Advisory Evaluation Validation

## Implementation Evidence (2026-10-07)

- Feature prerequisites resolved this directory and its specification/plan/tasks.
- Full PoC001 offline suite: **316 tests passed** after implementation. This includes
  policy, persistence, A2A, prompt, editor, UI and existing governance/history/RAG tests.
- Focused evaluation/prompt checks: **28 passed**; response/evaluation A2A checks:
  **12 passed**; Windows launcher checks: **15 passed**.
- The new UI workflow was tested through the actual Streamlit entrypoint with AppTest:
  generate, load baseline rules, save one rule, generate again; candidate unchanged.
  Direct external rule edits, evaluator outages, reload, disable/removal and no-op
  rule ordering were also covered without Azure/model calls.
- Existing response Prompty bodies, Search data and cloud configuration were not
  changed. Default-off clients retain the original no-source-body A2A contract.
- Initial A2A validation caught and corrected protobuf Struct metadata access before
  continuing; subsequent complete contract tests passed.
- Shared cross-platform hosting regression: **10 tests passed**. This does not
  claim Linux service installation or live Azure acceptance.
- Browser verification used a separate temporary localhost:8502 fixture rendering
  the real Streamlit app with synthetic answers, in-memory policies and guarded Azure
  clients. Generate/add baseline rule/save/generate showed one baseline finding with
  exact quotes and a new revision; candidate retained its original revision.
- Desktop (1440x1000) and narrow (390x844) main-content checks found no horizontal
  overflow. Screenshots of desktop findings, narrow findings and the Rules form
  confirmed readable wrapped text and no observed overlap in the inspected views.
  The fixture was stopped and removed; it was not a live service or model-quality test.
- Editor diagnostics reported no errors, `git diff --check` passed, and 59 local
  documentation links resolved. No dependencies or generation prompt bodies changed.
- No Spec Kit extension hooks or incomplete feature checklists were present.

## User-Authorized Activation (2026-10-07)

- Added only `ELV_ENABLE_EVALUATION="true"` to the existing external
  `C:\ProgramData\elv\poc001\runtime.json`. Verified all previous setting values
  and the file's security descriptor were unchanged. Local evaluator validation
  passed without token requests or Azure calls.
- Restarted the response agent and UI with the Windows launcher and started its
  evaluator component. Health checks passed for UI port 8501, response agent port
  9999 and evaluator port 10000; all three listeners were `127.0.0.1` only.
- The response Agent Card advertises the evaluation-evidence extension, and the
  evaluator Agent Card advertises the advisory-profile-evaluation skill.
- Navigated the shared browser from the stopped synthetic preview to the live UI
  at `http://127.0.0.1:8501`. Configuration > Rules loaded both baseline and candidate
  read-only through the existing managed-identity path. Both reported no stored
  rule policy and displayed the add-rule form without application errors.
- No Azure policy/configuration writes, Search queries or model inference were
  performed during activation. Existing endpoints, identity, RAG/history settings,
  index, grants and networking were preserved. A2A in-memory tasks/contexts were
  reset by restart; stored configuration was not reset.

## Semantic Judgment Repair (2026-10-07)

- A user-triggered candidate authorization check returned the generic semantic error.
  Its stored task showed a completed GPT-4o call with usage, distinguishing the failure
  from a connection outage. The original rejected judgment was not retained.
- User-approved evaluator-only diagnostics reproduced two contract defects: prompt-only
  JSON returned wrong fields/unrequested checks; a strict schema alone still allowed
  paraphrased or invented source quotations that failed exact-source validation.
- The evaluator now sends a strict `json_schema` response format and restricts output
  to requested profiles/rules and known text-passage IDs. It resolves quotations from
  the original input rather than accepting model-authored quotation text. Exact-text,
  per-profile scope, required-fact evidence and incomplete-evidence checks remain.
  The existing 2500-character retrieval cap is unchanged; this is not passage retrieval.
- Added safe failure-stage diagnostics and offline coverage for request forwarding,
  reference scope, unsupported IDs, original-text preservation and prior safeguards.
  **323 PoC001 tests passed**, including **38 focused evaluator/request/prompt checks**.
- Four additional model calls were explicitly authorized across two approvals and
  used for diagnosis/verification. One local transport attempt stopped before inference
  when snapshot integrity validation failed; original snapshots were then fetched
  directly with a UTF-8-aware HTTP client and their hashes rechecked. No response
  regeneration, Search query, Azure configuration write or rule change was performed.
- Final live A2A verification on the original response pair succeeded on
  `gpt-4o-2024-11-20` with API `2024-10-21`. Evaluation
  `8ed3621f-1e4e-45f1-bf4c-ce2bf00987cf` completed in 2.933 seconds, using 5254 prompt
  and 64 completion tokens. Candidate's authorization rule was `not_applicable`
  because the answer made no definite not-required assertion; its literal rule still
  found configured wording. Baseline remained `not_configured`.
- Only the evaluator process was restarted to deploy the fix. UI/response processes,
  user profiles and runtime JSON were unchanged. Existing displayed results are not
  rewritten; Generate requests a new comparison under the repaired evaluator.

## Intermittent Model Request Follow-Up (2026-10-07)

- A subsequent user evaluation `cf04e260-3e10-4c9b-a690-ba3c32fccb65` failed at
  `model_request` in 0.494 seconds, after two successful authorization evaluations.
  It had no completion/usage result. This timing did not support the configured
  35-second read-timeout hypothesis, but the original exception/status was not retained;
  no claim that the failure was specifically HTTP 429 or a network error is established.
- Added fixed SDK-based categories for rate limiting, timeout, connection failure,
  authentication/authorization denial, missing deployment, rejected request and service
  failure. Safe numeric Retry-After guidance is shown for 429/503 when provided.
  No raw provider body, URL, header text or exception detail is logged/displayed.
- The evaluator still makes at most one model call, without retries. Literal results,
  exact reference validation and uncertainty behavior are unchanged. An attempted
  model call without a response is now reported as model `not_reported`, not `not_called`.
- **325 PoC001 offline tests passed**, including **27 focused evaluator tests** covering
  request categories, cooldown bounds, preserved literal findings and no retry/leakage.
- User approved at most two additional evaluator-only calls. Both replays of the exact
  failed input succeeded without changing rules, generating new answers or querying
  Search. The deployed A2A replay `89ad36a1-09ee-4304-942f-ffb0bb25e447` completed in
  2.844 seconds, with 5352 prompt and 72 completion tokens. Candidate was `complete`:
  literal rule `no_finding`, authorization rule `not_applicable`; baseline remained
  `not_configured`. The candidate policy revision stayed unchanged.
- Only the evaluator was restarted. Runtime JSON, UI and response-agent processes,
  Azure endpoints, grants and stored rules were not modified. Improved diagnostics
  and successful replays do not prove the intermittent platform failure cannot recur.

## Remaining Acceptance

- Activation, live rule loading and the evaluator-only semantic regression above are
  verified. User-authored candidate rules were consumed without changing their values.
- The initial activation did not seed policies or run inference; the later explicitly
  approved diagnostic calls are recorded separately above.
- Synthetic/mocked judge tests prove contracts, not semantic accuracy. An approved
  live golden-set review must measure false positives/negatives, relevance,
  condition preservation, uncertainty, latency and extra token cost.
- The original intermittent request failure was not reproducible in the approved
  follow-up calls; its precise HTTP or transport cause remains unconfirmed.
- No claim of member-specific benefits/authorization determination, production gates,
  immutable evaluation audit, exclusion-preserving retrieval or per-user A2A isolation.