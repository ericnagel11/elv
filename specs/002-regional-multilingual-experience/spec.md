# Feature Specification: Regional and Multilingual Conversational Experience

**Feature Branch**: `002-regional-multilingual-experience`

**Created**: 2026-07-29

**Status**: Draft

**Input**: Customer note on regionality and overcoming language barriers, applied to the configuration, experimentation, and review model established in proof of concept 001.

## Overview

Proof of concept 001 made the assistant's voice and knowledge configurable. This specification extends the same model to market, language, and jurisdiction, so that serving an additional market is a content and review exercise rather than an engineering project.

The narrative form of this design is whitepaper section 1.3 and the regional and multilingual section in [`docs/configurable-conversational-experience.md`](../../docs/configurable-conversational-experience.md). This document is the testable specification behind it.

**Working markets**: `en-US`, `es-MX`, `de-DE`. These exercise three different parts of the problem. Spanish and German mark formality grammatically where English does not. German carries a jurisdiction whose consumer law contradicts United States commercial policy on the same customer question. All three are Latin script, which keeps the demonstration focused on governance rather than on text rendering.

**Central premise**: language is served by authored, reviewed assets and certified content. Runtime machine translation and model-native "answer in the customer's language" are deliberately excluded. Every string a customer reads in their language was written or certified by a person and is versioned.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Serve a Market in Its Own Language with Its Own Rules (Priority: P1)

A market owner configures a new market by supplying only the values that differ from the global default, together with reviewed content for that market. A customer in that market then asks a question and receives an answer that is in their language, in the register appropriate to the relationship, and grounded only in content written for their jurisdiction.

**Why this priority**: This is the whole proposition. If a market cannot be added through configuration and reviewed content alone, nothing else in this specification matters.

**Independent Test**: Configure `de-DE` with a formality override and a language-scoped retrieval filter, then ask a returns question in German and confirm the answer is in German, uses the formal register, and states the German policy rather than the United States policy.

**Acceptance Scenarios**:

1. **Given** a `de-DE` market profile that overrides only formality and the retrieval filter, **When** a session resolves for that market, **Then** the resolved profile combines the global defaults with the market overrides and records which layer supplied each value.
2. **Given** the same question asked in `en-US` and in `de-DE`, **When** both are answered, **Then** the substance differs according to each market's policy content and neither answer cites the other market's document.
3. **Given** a market with no overrides configured at all, **When** a session resolves for that market, **Then** the global default profile is used and the absence of overrides is visible rather than silent.

---

### User Story 2 - Prevent Uncertified Content from Reaching a Regulated Market (Priority: P1)

A compliance reviewer sets the minimum translation standard a document must meet before it may be used to answer customers in a given market. Content that does not meet the standard is unavailable to that market, and changing the standard is a governed, recorded act.

**Why this priority**: This is the control that makes the multilingual claim defensible. Without it, "we support German" means only that text appears in German.

**Independent Test**: With the `de-DE` gate set to require certified content, ask a question answered only by a reviewed-but-not-certified German document and confirm no answer is produced from it. Loosen the gate in the draft store as a designer, confirm the change cannot be published, publish it as an approver, and confirm the document now answers and that the change appears in the audit record.

**Acceptance Scenarios**:

1. **Given** a market whose gate requires certified content, **When** the only relevant document is machine translated or reviewed, **Then** that document does not contribute to the answer.
2. **Given** a designer identity, **When** the gate is loosened in the draft store, **Then** the edit succeeds in draft and publication to production is refused.
3. **Given** an approver identity, **When** the loosened gate is published, **Then** the previously excluded document becomes answerable and the change is attributable to that identity with a timestamp.
4. **Given** a document available in the market's language but written for a different jurisdiction, **When** a question is asked, **Then** that document does not contribute to the answer.

---

### User Story 3 - Guarantee Required Disclosures Reach the Customer Unaltered (Priority: P1)

A jurisdictional compliance reviewer approves notice text once, and every answer in that jurisdiction carries it exactly as approved.

**Why this priority**: A paraphrased mandatory notice is a compliance defect produced by an otherwise correct system. The control is cheap and the failure is expensive.

**Independent Test**: Configure a disclosure set for `de-DE`, generate several answers, and confirm the notice text is byte-identical to the approved asset in every one.

**Acceptance Scenarios**:

1. **Given** a market with a configured disclosure set, **When** any answer is produced, **Then** the approved notice text appears exactly as authored, with no rewording, shortening, or translation.
2. **Given** a market with no disclosure set configured, **When** an answer is produced, **Then** no notice is appended and the absence is a visible configuration state rather than an error.
3. **Given** a configured disclosure set whose asset cannot be resolved, **When** an answer is requested, **Then** the system does not produce an answer without the required notice.

---

### User Story 4 - Run an Experiment in One Market Without Disturbing the Others (Priority: P2)

An experience owner tests a candidate profile in a single market, ramps or stops it independently of every other market, and reads the result against that market's own baseline.

**Why this priority**: Market-scoped experimentation is the direct answer to the customer's question about applying A/B testing to regionality, but it depends on User Stories 1 and 2 being in place first.

**Independent Test**: Assign a candidate to a proportion of `de-DE` users, confirm `en-US` and `es-MX` assignment is unchanged, then stop the German experiment and confirm the other markets continue running.

**Acceptance Scenarios**:

1. **Given** an experiment scoped to one market, **When** allocation is changed for that market, **Then** assignment in other markets is unaffected.
2. **Given** an active experiment in one market, **When** its kill switch is operated, **Then** that market returns to its default variant immediately and other markets continue unchanged.
3. **Given** a customer assigned to a variant, **When** the conversation continues across turns, **Then** both the market and the variant remain stable for the session.
4. **Given** results from two markets, **When** they are reported, **Then** each market's outcome is expressed as change against that market's own baseline and no cross-market ranking on language-dependent measures is presented.

---

### User Story 5 - See What a Global Change Will Reach Before Publishing It (Priority: P2)

A global experience owner about to change a default can see which markets inherit that value and will therefore receive the change without a market review.

**Why this priority**: Sparse inheritance is what keeps the model economical, and it is also the mechanism by which an unreviewed change reaches a regulated market. The preview converts an invisible default into a reviewed decision.

**Independent Test**: Edit a global default for a key that two markets inherit and one market overrides, and confirm the preview names the two inheriting markets and excludes the third.

**Acceptance Scenarios**:

1. **Given** a pending change to a global default, **When** the change is reviewed before publication, **Then** the markets that inherit that key are listed.
2. **Given** a market that overrides the key being changed, **When** the same preview is produced, **Then** that market is shown as unaffected.

---

### User Story 6 - Detect Localized Content That Has Fallen Behind Its Source (Priority: P3)

A content steward sees which localized documents were certified against a version of their source document that has since been revised.

**Why this priority**: Drift is the permanent operating cost of multilingual content, but a demonstration remains credible without it, so it ranks below the controls that prevent bad answers today.

**Independent Test**: Revise a source document, then confirm the localized documents derived from the previous version are reported as behind, with the version gap shown.

**Acceptance Scenarios**:

1. **Given** a localized document derived from a source version, **When** the source is revised, **Then** the localized document is reported as behind its source.
2. **Given** a localized document derived from the current source version, **When** the report is produced, **Then** it is reported as current.

---

### Edge Cases

- **No content meets the market's gate for the question asked.** The system must not answer from another market's content by default. Fallback behavior is specified in the whitepaper and is out of scope for this proof of concept; the demonstrated behavior is to decline and offer the market's escalation path.
- **The model answers in the wrong language,** most often reverting to the source language when retrieved context is in that language. The configured language-adherence setting determines whether this is suppressed, recorded, or ignored.
- **A global default changes for a key no market overrides.** Every market receives it. This is the intended behavior and must be visible before publication rather than discovered afterwards.
- **Two markets share a language but not a jurisdiction,** such as `de-DE` and a prospective `de-AT`. Language-level assets are shared; jurisdiction-scoped content and disclosures are not.
- **A market label exists with no overrides.** The market resolves entirely to global defaults, which is valid and must be distinguishable from a misconfigured market.
- **A source document is withdrawn while certified translations of it remain.** The translations must not continue answering on the strength of a source that no longer exists.
- **Retrieval returns content in a language the market does not serve.** The filter must exclude it rather than relying on the model to notice.

## Requirements *(mandatory)*

### Functional Requirements

#### Market resolution

- **FR-001**: The system MUST resolve a market profile from a layered chain in which a global default layer is overridden by a market layer and then by an experiment layer, with the most specific value winning.
- **FR-002**: A market layer MUST be able to carry only the values that differ from the global default, and MUST NOT be required to restate inherited values.
- **FR-003**: The resolved profile MUST record, for every value, which layer supplied it.
- **FR-004**: The market and the experiment variant MUST both be resolved once at the start of a session and remain stable for its duration.
- **FR-005**: A change of language during a conversation MUST begin a new session and MUST be recorded as a transition rather than applied to the session in progress.
- **FR-006**: The system MUST be able to report, for a proposed change to a global default, the list of markets that inherit the affected value.

#### Language assets

- **FR-007**: The system MUST resolve a prompt asset by selecting the most specific available asset for the market, falling back to a language-level asset and then to a language-neutral asset.
- **FR-008**: A market-specific or language-specific prompt asset MUST exist only where that market or language requires different instructions, and its absence MUST NOT prevent the market from operating.
- **FR-009**: The system MUST support a formality setting whose meaning is expressed in the terms of the target language.
- **FR-010**: The system MUST inject an approved terminology set, including terms that must not be translated, into the instructions for the market.
- **FR-011**: The system MUST NOT perform runtime machine translation of generated responses, and MUST NOT rely on the model choosing a response language unprompted.

#### Knowledge and certification

- **FR-012**: Every knowledge document MUST carry the language it is written in, the jurisdiction whose rules it states, and the level of human review that stands behind its text.
- **FR-013**: Every localized knowledge document MUST identify the source document and the source version it was derived from.
- **FR-014**: Retrieval scope MUST be expressible as configuration covering approval status, language, jurisdiction, and required review level, without a change to application code.
- **FR-015**: Each market MUST declare a minimum review level, and content below that level MUST NOT contribute to answers in that market.
- **FR-016**: Content written for a jurisdiction the market does not belong to MUST NOT contribute to answers in that market, except where the content is explicitly marked as applying globally.
- **FR-017**: The system MUST be able to report localized documents whose recorded source version is behind the current version of their source document, including the size of the gap.
- **FR-018**: Changing a market's minimum review level MUST follow the same propose, approve, and publish path as any other configuration change, and MUST be attributable to an identity with a timestamp.

#### Disclosures

- **FR-019**: Jurisdictionally required notice text MUST be stored as an approved, versioned asset and MUST reach the customer without modification.
- **FR-020**: Required notice text MUST NOT be produced by the language model, and MUST NOT be passed through the model in a way that permits rewording, abridgement, or translation.
- **FR-021**: Where a market is configured to require a notice and that notice cannot be resolved, the system MUST NOT return an answer for that market.

#### Experimentation

- **FR-022**: An experiment MUST be scoped to a single market, and its allocation MUST be adjustable without affecting allocation in any other market.
- **FR-023**: Each market's experiment MUST have an independent stop control that returns only that market to its default experience.
- **FR-024**: Outcome measurement MUST distinguish measures that are comparable across languages from measures that are not, and MUST report language-dependent measures only against the same market's baseline.
- **FR-025**: Readability MUST be measured using a formula appropriate to the language being measured, and readability values from different languages MUST NOT be compared to one another.
- **FR-026**: The market MUST be recorded alongside the assigned variant in experiment telemetry.
- **FR-027**: Each market's experiment MUST have its own pre-registered primary measure, minimum detectable effect, and expected duration, recorded before exposure begins.

#### Governance and audit

- **FR-028**: The system MUST distinguish the role that approves language, register, and terminology for a market from the role that approves jurisdictional content and notices, and from the role that owns terminology across markets.
- **FR-029**: Permission to change one market's values MUST NOT confer permission to change another market's values.
- **FR-030**: Where the platform cannot enforce market-level separation directly, the specification MUST identify the compensating control used and MUST NOT describe the separation as platform-enforced.
- **FR-031**: Every configuration change affecting a market MUST be recorded with the identity that made it, the value affected, and the time.
- **FR-032**: Evidence of linguistic and compliance sign-off MUST be associated with the change it approves, rather than being held as an assumption about who holds a role.

#### Quality measurement

- **FR-033**: Each market MUST have a fixed set of representative questions with expected behaviors, runnable against a candidate before customer exposure.
- **FR-034**: The system MUST detect the language of a generated response and compare it to the market's expected language.
- **FR-035**: The action taken when a response is in an unexpected language MUST be configurable per market, covering at least suppression, recording, and disabling the check.
- **FR-036**: A sample of live answers per market MUST be reviewable by a speaker of that language, scored on register, terminology, and accuracy.

#### Scope boundaries

- **FR-037**: Fallback behavior for questions with no qualifying content MUST be documented as a governed, per-market decision, and MUST NOT be implemented in this proof of concept.
- **FR-038**: Data residency, in-region processing, formatting conventions for currency, dates and units, and right-to-left rendering are out of scope and MUST be identified as separate concerns rather than treated as solved.
- **FR-039**: Every capability relied upon MUST be identified as generally available or preview at the time of writing, and a preview capability MUST NOT be selected where a generally available alternative satisfies the outcome.

### Key Entities

- **Market Profile**: The resolved set of experience, market, and knowledge values for one market, together with the provenance of each value.
- **Layer**: One contributing set of values in the resolution chain, being the global default, a market override, or an experiment override.
- **Localized Prompt Asset**: A versioned instruction template scoped to a market or a language, selected by resolution rather than named directly in configuration.
- **Glossary**: A versioned, per-language set of approved terms and terms that must not be translated.
- **Knowledge Document**: A content item carrying approval status, audience, industry, effective date, language, jurisdiction, review level, source document identity, and source version.
- **Review Level**: The degree of human assurance behind a document's text, ordered from unreviewed machine output through in-market review to formal certification.
- **Certification Gate**: The minimum review level a market requires before a document may contribute to its answers.
- **Disclosure Asset**: Approved notice text for a jurisdiction, versioned and delivered verbatim.
- **Market Experiment**: An allocation of variants within a single market, with its own stop control, pre-registered measures, and telemetry.
- **Market Reviewer Role**: An accountability for a defined subset of markets or jurisdictions, distinct from the platform roles that govern the configuration store.
- **Drift Report**: The comparison between a localized document's recorded source version and the current version of its source.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An additional market can be brought into service by supplying market values and reviewed content only, with no change to application code and no application deployment.
- **SC-002**: The same customer question asked in two markets returns answers whose substance reflects each market's own policy, with no citation of the other market's content, in 100 percent of trials across the prepared question set.
- **SC-003**: Content below a market's required review level contributes to zero answers in that market across the prepared question set.
- **SC-004**: Required notice text appears byte-identical to its approved asset in 100 percent of answers produced for a market that requires it.
- **SC-005**: An unauthorized identity attempting to publish a market change is refused by the platform or the compensating control, and the refusal is visible to the person attempting it.
- **SC-006**: Changing a market's certification gate is attributable to a specific identity, with a timestamp, within the audit record.
- **SC-007**: Adjusting or stopping an experiment in one market produces no change in variant assignment for any other market.
- **SC-008**: A proposed change to a global default reports the complete and correct set of markets that inherit the affected value, verified against the configured overrides.
- **SC-009**: A localized document whose source has been revised is reported as behind within one reporting cycle of the source change.
- **SC-010**: A response generated in an unexpected language is detected, and the configured action is taken, in at least 95 percent of induced cases.
- **SC-011**: A reviewer can determine, for any value in a resolved market profile, which layer supplied it, without inspecting the configuration store directly.
- **SC-012**: The demonstration of market, certification, and experimentation behavior is executable in 15 minutes or less after setup.

## Assumptions

- Proof of concept 001 is the reference implementation for the configuration, prompt asset, retrieval, role, and audit mechanisms this specification extends. Those mechanisms are treated as proven and are not re-specified here.
- Proof of concept 002 is delivered as its own folder with its own provisioning and teardown, reusing the module structure and script patterns of proof of concept 001, so that each proof of concept can be set up and removed independently.
- Sample content is synthetic. German and Spanish content is authored for the demonstration and is not legal advice; the certification levels attached to it are illustrative of the workflow rather than statements about real regulatory review.
- The jurisdictional contrast used in the demonstration is the difference between a statutory withdrawal right and a commercial return window on the same customer question. Exact legal wording is out of scope and would require real legal review before any production use.
- Three markets are sufficient to demonstrate the model. Adding a fourth is expected to be a content and configuration exercise, and that expectation is itself part of what the demonstration tests.
- Traffic volumes in a demonstration are too small for statistical significance. Experimentation is demonstrated as a mechanism, including scoping and stop controls, rather than as a concluded experiment.
- Role separation in the demonstration uses distinct service principals, as in proof of concept 001. Production would use managed identity, workload identity federation, and group-based assignment.

## Dependencies

- A configuration store supporting labels, a separate draft store, and diagnostic logging, as established in proof of concept 001.
- A retrieval service supporting metadata filtering, per-field language analysis, and an indirection between the name an application queries and the concrete index behind it.
- A model deployment reachable through workforce or workload identity rather than keys.
- An experimentation mechanism supporting per-market allocation and an independent stop control per market.
- A language detection capability for the adherence guardrail.
- Named human reviewers per market and per jurisdiction. This is a staffing dependency rather than a technical one, and the design does not function without it.

## Out of Scope

- Runtime machine translation of responses, and any fallback path that depends on it.
- Model-native language selection as a substitute for authored assets.
- Data residency and in-region processing.
- Formatting conventions for currency, dates, units, addresses, and telephone numbers.
- Right-to-left scripts and the rendering concerns they introduce.
- Voice, telephony, and speech localization.
- Automated translation quality scoring.

## Appendix: Build Backlog

This appendix records what a later implementation touches, using proof of concept 001 as the structural template. It is a planning aid and not a requirement.

| Area | Change |
|---|---|
| Configuration loading | Layered resolution across the global, market, and experiment labels, returning both values and the layer that supplied each |
| Prompt resolution | Most-specific-first asset lookup across market, language, and neutral variants |
| Retrieval | Additional selected fields for language, jurisdiction, review level, source document, and source version, and composition of the market filter from configuration |
| Content metadata | The same fields added to the knowledge manifest and mapped into the index |
| Index topology | One index per language behind a stable query-time alias, with each indexer targeting its concrete index |
| Disclosures | Deterministic append of the resolved disclosure asset after generation, outside the model call |
| Seeding | Market profiles for the three working markets, with sparse overrides rather than full profiles |
| Interface | Market selection, provenance display per value, and the inheritance preview for a pending global change |
| Roles | Market owner, jurisdictional compliance reviewer, and terminology owner added to the role fixtures |
| Reporting | Drift comparison between localized documents and their sources |
