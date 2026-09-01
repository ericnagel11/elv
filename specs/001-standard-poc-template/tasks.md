---

description: "Architect and consultant backlog for configuring and validating each proof-of-concept scenario"
---

# Tasks: Standard Proof-of-Concept Template

**Input**: Design documents from `specs/001-standard-poc-template/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `quickstart.md`

**Execution unit**: Repeat every task in Phases 3 through 5 for each proof-of-concept scenario. Replace `<scenario-id>` with a stable scenario identifier in every path.

**Organization**: Tasks are grouped by user story. Each story separates mandatory delivery work from optional enhancements and can be validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it updates a different artifact and has no dependency on an incomplete task
- **[Story]**: Maps the task to its user story
- Every task identifies the artifact where the consultant records the result

## Phase 1: Setup (Shared Engagement Infrastructure)

**Purpose**: Establish controlled locations, naming, ownership, and reusable working templates.

### Mandatory Tasks

- [ ] T001 Create the scenario register with scenario ID, title, owner, priority, status, and target validation date in `deliverables/scenario-register.xlsx`
- [ ] T002 Create the standard 13-section working document from the feature specification in `deliverables/templates/proof-of-concept-template.docx`
- [ ] T003 [P] Create the architecture diagram legend and boundary conventions in `deliverables/templates/architecture-legend.pptx`
- [ ] T004 [P] Create the evidence index with checkpoint, artifact, owner, date, and secure location fields in `deliverables/templates/evidence-index.xlsx`
- [ ] T005 Define document, sample-data, and evidence access permissions and retention rules in `deliverables/engagement-governance.md`

### Optional Enhancements

- [ ] T006 [P] Configure a Microsoft Teams or SharePoint workspace with channels or folders for scenarios, data, evidence, and reviews and record its structure in `deliverables/collaboration-workspace.md`
- [ ] T007 [P] Create reusable Microsoft Lists for risks, decisions, actions, and validation checkpoints and record list URLs in `deliverables/collaboration-workspace.md`

**Checkpoint**: Shared templates, controlled storage, ownership, and scenario identifiers are ready.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the common governance decisions that every scenario must inherit.

**CRITICAL**: Complete this phase before beginning any scenario configuration.

### Mandatory Tasks

- [ ] T008 Document approved Azure subscriptions, management groups, regions, naming rules, tagging rules, resource-group pattern, and budget ownership in `deliverables/foundation/azure-guardrails.md`
- [ ] T009 [P] Document approved Microsoft 365 tenants, test-user pattern, available licenses, administrative roles, consent process, and tenant-change approval path in `deliverables/foundation/microsoft-365-guardrails.md`
- [ ] T010 [P] Document Microsoft Entra identity, least-privilege access, privileged role activation, service principal, managed identity, and guest-access rules in `deliverables/foundation/identity-access.md`
- [ ] T011 [P] Document approved network exposure, private connectivity, firewall, endpoint, and external dependency patterns in `deliverables/foundation/network-security.md`
- [ ] T012 [P] Define sample-data classification, synthetic-data default, sanitization approval, secure transfer, retention, and deletion requirements in `deliverables/foundation/sample-data-policy.md`
- [ ] T013 Define cost estimation date, currency, agreement assumptions, Azure Pricing Calculator method, Microsoft 365 licensing source, exclusions, and cleanup expectations in `deliverables/foundation/cost-method.md`
- [ ] T014 Define the common evidence standard, pass/fail/block status, variance handling, secret-redaction check, and independent validator role in `deliverables/foundation/validation-standard.md`

### Optional Enhancements

- [ ] T015 [P] Define reusable Azure Policy, resource lock, diagnostic setting, and budget alert recommendations for proof-of-concept environments in `deliverables/foundation/optional-azure-controls.md`
- [ ] T016 [P] Define reusable Microsoft Purview labeling, retention, audit, and data loss prevention recommendations for proof-of-concept artifacts in `deliverables/foundation/optional-m365-controls.md`

**Checkpoint**: Azure, Microsoft 365, identity, network, data, cost, and validation guardrails are approved for scenario use.

---

## Phase 3: User Story 1 - Create a Complete Proof of Concept (Priority: P1) MVP

**Goal**: Produce a complete, scenario-specific deliverable that identifies and configures all required Azure resources, Microsoft 365 capabilities, sample data, and success criteria.

**Independent Test**: Review `deliverables/<scenario-id>/proof-of-concept.docx` and confirm all 13 sections are present in order with scenario-specific content or an explicit not-applicable rationale.

### Mandatory Tasks for Every Scenario

- [ ] T017 [US1] Define the business objective, stakeholders, scope, exclusions, measurable value, assumptions, and decision sought in `deliverables/<scenario-id>/01-business-scenario.md`
- [ ] T018 [P] [US1] Inventory required Azure services with purpose, subscription, resource group, region, SKU, quota, identity, network mode, tags, owner, cost driver, and cleanup action in `deliverables/<scenario-id>/02-azure-resources.xlsx`
- [ ] T019 [P] [US1] Inventory required Microsoft 365 workloads and capabilities with tenant, license, admin role, user role, consent, policy impact, dependency, configuration location, and rollback owner in `deliverables/<scenario-id>/03-microsoft-365-capabilities.xlsx`
- [ ] T020 [P] [US1] Define the synthetic or sanitized sample-data package with source, classification, schema, format, volume, generation method, expected records, handling, retention, and cleanup in `deliverables/<scenario-id>/04-sample-data-plan.md`
- [ ] T021 [US1] Produce the scenario architecture showing Azure resources, Microsoft 365 services, identities, connections, data flows, trust boundaries, external dependencies, and legend in `deliverables/<scenario-id>/05-architecture.pptx`
- [ ] T022 [US1] Confirm Azure subscription access, provider registration, regional availability, quota, resource naming, tags, budget owner, and required approvals and record outcomes in `deliverables/<scenario-id>/06-prerequisite-checklist.md`
- [ ] T023 [US1] Confirm Microsoft 365 tenant readiness, licenses, test users, administrative roles, consent, audit availability, and change approvals and record outcomes in `deliverables/<scenario-id>/06-prerequisite-checklist.md`
- [ ] T024 [US1] Configure the required Azure resources in dependency order and record portal location, responsible role, non-secret inputs, expected checkpoint, evidence, and recovery guidance in `deliverables/<scenario-id>/07-configuration-runbook.md`
- [ ] T025 [US1] Configure the required Microsoft 365 capabilities and record workload settings, assigned licenses, roles, consent, policy changes, validation observations, and rollback guidance in `deliverables/<scenario-id>/07-configuration-runbook.md`
- [ ] T026 [US1] Generate or sanitize the approved sample data, verify its schema and volume, load it into the scenario, and record the loading checkpoint in `deliverables/<scenario-id>/08-sample-data-register.xlsx`
- [ ] T027 [US1] Define presenter preparation, actions, narration, expected observations, timing, evidence capture, reset, and cleanup in `deliverables/<scenario-id>/09-demonstration-script.md`
- [ ] T028 [US1] Define objective pass criteria and expected results before demonstration execution in `deliverables/<scenario-id>/10-results-register.xlsx`
- [ ] T029 [US1] Assemble the executive summary, solution overview, architecture, components, configuration, sample data, demonstration, and expected results into all required sections of `deliverables/<scenario-id>/proof-of-concept.docx`
- [ ] T030 [US1] Complete a section-order, internal-reference, evidence, data-classification, credential-redaction, and not-applicable rationale review in `deliverables/<scenario-id>/11-completeness-checklist.md`

### Optional Enhancements for Every Scenario

- [ ] T031 [P] [US1] Add secondary architecture views for identity, network, data flow, or responsibility boundaries in `deliverables/<scenario-id>/optional/detailed-architecture.pptx`
- [ ] T032 [P] [US1] Configure Azure budgets, diagnostic settings, resource locks, or policy assignments approved for the scenario and record evidence in `deliverables/<scenario-id>/optional/azure-controls.md`
- [ ] T033 [P] [US1] Configure Microsoft Purview labels, retention, audit, or data loss prevention controls approved for the scenario and record evidence in `deliverables/<scenario-id>/optional/microsoft-365-controls.md`

**Checkpoint**: The scenario has a complete 13-section deliverable and a working configured environment ready for independent reproduction.

---

## Phase 4: User Story 2 - Reproduce the Demonstration (Priority: P2)

**Goal**: Enable a consultant unfamiliar with the original setup to reproduce the scenario and diagnose any failed checkpoint without undocumented decisions.

**Independent Test**: Provide only the completed scenario package and stated prerequisites to an independent consultant; confirm the primary demonstration is reproduced within 120 minutes, excluding provisioning and approval waits.

### Mandatory Tasks for Every Scenario

- [ ] T034 [P] [US2] Review every Azure configuration action for explicit portal path, role, input, expected checkpoint, validation, evidence, recovery, and cleanup detail in `deliverables/<scenario-id>/12-reproduction-review.md`
- [ ] T035 [P] [US2] Review every Microsoft 365 configuration action for explicit admin center path, license, role, consent, tenant setting, validation, rollback, and policy-impact detail in `deliverables/<scenario-id>/12-reproduction-review.md`
- [ ] T036 [P] [US2] Verify that the sample-data package can be regenerated or reloaded from its documented source and instructions and record counts and exceptions in `deliverables/<scenario-id>/13-data-reproduction-results.xlsx`
- [ ] T037 [US2] Assign an independent consultant who did not configure the scenario and record independence, prerequisites supplied, start time, and environment in `deliverables/<scenario-id>/14-independent-validation.md`
- [ ] T038 [US2] Have the independent consultant execute the Azure and Microsoft 365 configuration runbook, recording each checkpoint as passed, failed, or blocked in `deliverables/<scenario-id>/15-checkpoint-results.xlsx`
- [ ] T039 [US2] Have the independent consultant load the sample data and execute the complete demonstration script, recording elapsed time, observations, evidence, and reset outcome in `deliverables/<scenario-id>/16-demonstration-results.md`
- [ ] T040 [US2] Compare actual and expected results, document variances and likely causes without rewriting expectations, and assign corrective actions in `deliverables/<scenario-id>/10-results-register.xlsx`
- [ ] T041 [US2] Update ambiguous steps and recovery guidance found during reproduction, then obtain validator sign-off in `deliverables/<scenario-id>/17-reproduction-signoff.md`

### Optional Enhancements for Every Scenario

- [ ] T042 [P] [US2] Record a narrated demonstration and link the approved recording with timestamps to the script in `deliverables/<scenario-id>/optional/recording-index.md`
- [ ] T043 [P] [US2] Run a second reproduction using a clean resource group or test tenant boundary and compare both runs in `deliverables/<scenario-id>/optional/repeatability-results.xlsx`

**Checkpoint**: An independent consultant has reproduced the scenario or documented an actionable variance at every failed or blocked checkpoint.

---

## Phase 5: User Story 3 - Evaluate Readiness and Tradeoffs (Priority: P3)

**Goal**: Give decision-makers sufficient security, cost, production readiness, and lessons-learned information to decide whether and how to continue.

**Independent Test**: A reviewer can identify the top risks, cost drivers, production gaps, lessons, and recommended next decision from the governance sections within 15 minutes.

### Mandatory Tasks for Every Scenario

- [ ] T044 [P] [US3] Assess identities, privileges, data protection, network exposure, secrets, monitoring, audit, compliance obligations, risks, mitigations, and residual risk in `deliverables/<scenario-id>/18-security-assessment.md`
- [ ] T045 [P] [US3] Estimate proof-of-concept and projected ongoing Azure costs with dated assumptions, usage, scaling, included and excluded items, cleanup effects, and pricing source in `deliverables/<scenario-id>/19-cost-assessment.xlsx`
- [ ] T046 [P] [US3] Assess Microsoft 365 license prerequisites, add-on requirements, tenant-level impacts, trial constraints, and projected licensing considerations in `deliverables/<scenario-id>/19-cost-assessment.xlsx`
- [ ] T047 [P] [US3] Assess production gaps for reliability, scalability, performance, operations, support, governance, security, compliance, data management, deployment, testing, and business continuity in `deliverables/<scenario-id>/20-production-readiness.md`
- [ ] T048 [US3] Record successful approaches, challenges, unexpected findings, limitations, reusable insights, and recommended changes in `deliverables/<scenario-id>/21-lessons-learned.md`
- [ ] T049 [US3] Define the recommended next decision, accountable owner, required approvals, dependencies, target date, and explicitly out-of-scope production work in `deliverables/<scenario-id>/22-recommendation.md`
- [ ] T050 [US3] Incorporate security, cost, production, lessons, actual results, and recommendation content into the corresponding sections of `deliverables/<scenario-id>/proof-of-concept.docx`
- [ ] T051 [US3] Conduct a 15-minute decision-maker review and record whether the objective, outcome, top risks, cost drivers, production gaps, and next decision were identifiable in `deliverables/<scenario-id>/23-decision-review.md`

### Optional Enhancements for Every Scenario

- [ ] T052 [P] [US3] Model low, expected, and high Azure usage and Microsoft 365 licensing scenarios in `deliverables/<scenario-id>/optional/cost-sensitivity.xlsx`
- [ ] T053 [P] [US3] Create a phased production roadmap with dependencies, decision gates, and indicative ownership in `deliverables/<scenario-id>/optional/production-roadmap.pptx`

**Checkpoint**: The scenario package supports an informed proceed, revise, pause, or stop decision without implying production approval.

---

## Phase 6: Polish & Cross-Cutting Handoff

**Purpose**: Complete portfolio-level consistency, cleanup, and handoff after the selected scenarios are finished.

### Mandatory Tasks

- [ ] T054 Reconcile scenario status, outcomes, blockers, owners, and next decisions in `deliverables/scenario-register.xlsx`
- [ ] T055 Run the complete validation procedure in `specs/001-standard-poc-template/quickstart.md` for every completed scenario and record exceptions in `deliverables/final-validation.md`
- [ ] T056 Verify all temporary Azure resources, trial licenses, test users, external sharing links, sample data, and credentials are removed, disabled, retained, or handed over as documented in `deliverables/cleanup-register.xlsx`
- [ ] T057 Confirm final files are versioned, accessible to intended recipients, free of secrets and unapproved data, and listed in `deliverables/handoff-inventory.xlsx`

### Optional Enhancements

- [ ] T058 [P] Create a cross-scenario comparison of value, complexity, risk, cost, readiness, and recommended priority in `deliverables/optional/scenario-comparison.xlsx`
- [ ] T059 [P] Create an executive portfolio readout summarizing outcomes and next decisions in `deliverables/optional/executive-readout.pptx`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1** starts immediately.
- **Phase 2** depends on Phase 1 and blocks scenario work.
- **Phases 3 through 5** repeat for every scenario after Phase 2.
- For a given scenario, Phase 4 depends on its Phase 3 configuration and package.
- For a given scenario, Phase 5 can begin after Phase 3; final actual-result and lessons tasks depend on Phase 4.
- Different scenarios may proceed in parallel after Phase 2.
- **Phase 6** depends on all selected mandatory scenario phases.
- Optional enhancements never block mandatory completion.

### User Story Dependencies

- **US1 (P1)**: Depends only on the shared foundation.
- **US2 (P2)**: Depends on the US1 package for the same scenario.
- **US3 (P3)**: Security, cost, and production assessments can start after US1; final lessons and recommendation use US2 results.

### Parallel Opportunities

- Azure inventory, Microsoft 365 inventory, and sample-data planning can proceed in parallel for a scenario.
- Azure and Microsoft 365 readiness checks can proceed in parallel when performed by separate authorized roles.
- Security, Azure cost, Microsoft 365 licensing, and production-readiness assessments can proceed in parallel.
- Different scenarios can be configured and assessed in parallel after foundational approval.
- Tasks marked `[P]` produce separate artifacts or independent sections.

## Parallel Example: User Story 1

```text
Architect A: T018 - Azure resource inventory
Consultant B: T019 - Microsoft 365 capability inventory
Data lead: T020 - Sample-data plan
```

## Parallel Example: User Story 2

```text
Azure reviewer: T034 - Azure runbook review
Microsoft 365 reviewer: T035 - Microsoft 365 runbook review
Data reviewer: T036 - Sample-data reproducibility check
```

## Parallel Example: User Story 3

```text
Security architect: T044 - Security assessment
Cloud economist: T045 - Azure cost assessment
Licensing consultant: T046 - Microsoft 365 licensing assessment
Production architect: T047 - Production-readiness assessment
```

## Implementation Strategy

### MVP First

1. Complete shared Setup and Foundational phases.
2. Select one priority scenario.
3. Complete all mandatory US1 tasks for that scenario.
4. Stop and validate the 13-section deliverable independently.
5. Continue to reproduction and readiness only after the core scenario package is complete.

### Incremental Delivery

1. Deliver one complete configured scenario.
2. Prove independent reproduction.
3. Add decision-support assessments.
4. Repeat the mandatory backlog for each additional scenario.
5. Add optional enhancements only where they improve a decision or reduce material risk.

### Consultant Staffing

- Engagement lead: business scope, executive content, decisions, and handoff
- Azure architect: subscriptions, resources, identity, network, cost, and cleanup
- Microsoft 365 consultant: tenant, licensing, roles, consent, policies, and workload configuration
- Data owner: sample-data approval, generation, loading, retention, and cleanup
- Independent validator: reproduction, evidence, variance, and sign-off
- Security or production specialists: focused review where risk or target state requires it

## Notes

- Mandatory tasks define the minimum acceptable scenario package.
- Optional enhancements must not delay mandatory validation unless a reviewer promotes one to a required risk treatment.
- Record secure references and retrieval instructions, never secrets or credential values.
- Preserve expected results when actual results differ; record the variance and likely cause.
- Retain every required section and use an explicit not-applicable rationale where necessary.
