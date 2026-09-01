<!--
SYNC IMPACT REPORT
Version change: none → 1.0.0 (initial ratification)
Bump rationale: First adoption of the project constitution establishes the full governance
baseline (MAJOR baseline release).

Principles defined (12):
- I. Generally Available First
- II. Low-Cost, Low-Complexity Footprint
- III. Simplest Viable Implementation
- IV. Configuration Over Custom Code
- V. Reproducibility by Others
- VI. Security, Governance & Responsible AI by Design
- VII. Human Oversight & Transparency
- VIII. Interoperability & Modularity
- IX. Observability & Traceability
- X. Maintainability & Learning Value
- XI. Proof-of-Concept vs. Production Distinction
- XII. Clarity First

Added sections:
- Technology & Delivery Constraints
- Development Workflow & Quality Gates
- Governance

Removed sections: none (initial creation)

Templates reviewed for consistency:
- ✅ .specify/templates/plan-template.md — "Constitution Check" gate references the constitution
  dynamically and adds no conflicting rules; aligned, no change required.
- ✅ .specify/templates/spec-template.md — no new mandatory spec sections introduced by this
  constitution; aligned, no change required.
- ✅ .specify/templates/tasks-template.md — cross-cutting phase already covers security,
  documentation, and observability task types; aligned, no change required.
- ✅ .github/skills/speckit-*/SKILL.md — generic Spec Kit guidance; no outdated agent-specific
  references requiring change.
- ✅ docs/reference-architecture-standard.md — consistent with Principles I, II, IV, VI, IX;
  referenced from Governance as runtime guidance.

Follow-up TODOs: none.
-->

# Enterprise AI Proof-of-Concept Framework Constitution

## Core Principles

### I. Generally Available First

Proofs of concept (PoCs) MUST be built on generally available (GA) Microsoft and Azure
capabilities. Preview, beta, or private-preview features MUST NOT be used when a GA capability
can demonstrate the same concept. When no GA alternative exists, the preview dependency MUST be
explicitly identified together with its risk and a documented GA migration path.

**Rationale**: GA services provide the stability, support, and reproducibility that let other
practitioners rely on and reproduce a demonstration with confidence.

### II. Low-Cost, Low-Complexity Footprint

Every PoC MUST be deployable within a single standard Azure subscription using default quotas.
Solutions MUST NOT require specialized hardware (for example, GPUs), excessive compute, dedicated
or always-on infrastructure, or region-specific services unless the concept itself cannot be shown
otherwise; any such exception MUST be documented. Cost drivers and cleanup steps MUST be stated.

**Rationale**: Low cost and low complexity keep PoCs accessible, disposable, and safe to run for
demonstrations, workshops, architectural discussions, and customer envisioning sessions.

### III. Simplest Viable Implementation

A PoC MUST demonstrate its business and technical concept through the simplest implementation that
proves feasibility, the architecture pattern, and the configuration-driven approach.
Production-scale performance, optimization, high availability, and enterprise hardening are out of
scope unless one of them IS the concept being proven.

**Rationale**: The goal is to prove the idea, not to ship a product; scope discipline keeps PoCs
fast to build and easy to understand.

### IV. Configuration Over Custom Code

Solutions MUST prefer configuration, orchestration, prompts, workflows, agents, connectors,
policies, and platform capabilities over custom code. Custom development is permitted only where
platform configuration alone cannot reasonably demonstrate the concept, and each such instance MUST
be justified in the PoC's complexity or decision record.

**Rationale**: Configuration-led delivery is the central thesis of this framework and yields
solutions that are easier to reproduce, govern, and maintain.

### V. Reproducibility by Others

Every PoC MUST be reproducible by another qualified practitioner using only the documented setup
instructions, sample data, and clearly defined prerequisites. Setup steps MUST be explicit and
ordered; sample data MUST be synthetic or sanitized; secrets MUST appear only as secure
placeholders with retrieval instructions.

**Rationale**: A PoC that cannot be independently reproduced is a report, not a proof.

### VI. Security, Governance & Responsible AI by Design

Each PoC MUST apply least-privilege access, managed secret handling, and data protection
appropriate to the data classification, and MUST follow responsible AI practices, while avoiding
complexity that does not serve the demonstration. Confidential, personal, regulated, or
customer-owned data MUST NOT be used without documented approval and protection.

**Rationale**: Even minimal PoCs establish patterns that must be safe to adopt and extend into
real-world environments.

### VII. Human Oversight & Transparency

AI-driven decisions, recommendations, and automated actions MUST be explainable and reviewable by a
human operator. A PoC MUST provide a point of human review for consequential actions and MUST
surface the evidence behind AI outputs — such as citations, inputs, confidence, or a reasoning
summary.

**Rationale**: Trust in enterprise AI depends on humans being able to understand, review, and
override automated behavior.

### VIII. Interoperability & Modularity

Solutions SHOULD be interoperable, modular, and vendor-aware, using standards-based interfaces and
clear architectural boundaries. Components MUST have well-defined responsibilities and interfaces so
that a reviewer can understand each part and substitute it where practical.

**Rationale**: Modular, standards-based designs adapt to real-world environments and communicate
patterns more clearly than monolithic implementations.

### IX. Observability & Traceability

Each PoC MUST provide observability and traceability sufficient to follow data flow, prompt flow,
agent actions, decisions, and expected outcomes. Telemetry SHOULD correlate user actions, agent
activity, application calls, and data access end to end.

**Rationale**: Practitioners can only trust, debug, and evolve a solution they can observe.

### X. Maintainability & Learning Value

Every PoC MUST be built as a reference implementation that favors maintainability and learning value
over sophistication. Artifacts MUST help architects, consultants, and developers understand the
underlying pattern and adapt it to their scenarios. Cleverness that obscures the pattern MUST be
avoided.

**Rationale**: The lasting value of a PoC is the reusable understanding it transfers to others.

### XI. Proof-of-Concept vs. Production Distinction

Documents and artifacts MUST clearly distinguish PoC assumptions from production recommendations,
identifying limitations, scaling considerations, security hardening needs, and operational
requirements necessary for enterprise deployment. Demonstrated capabilities MUST NOT be presented as
production-ready.

**Rationale**: Honest boundaries prevent PoCs from being mistaken for production systems and inform
sound go/no-go decisions.

### XII. Clarity First

Architecture diagrams, specifications, prompts, workflows, and code samples MUST be concise, well
documented, and understandable by practitioners who are new to the technology stack. Diagrams MUST
include legends and boundaries, and instructions MUST avoid undocumented assumptions.

**Rationale**: Clarity is the primary success measure of this framework and determines whether a PoC
can be reused and adapted.

## Technology & Delivery Constraints

- **Platform baseline**: Prefer Microsoft and Azure GA services first, and Azure managed or
  serverless services before self-hosted components. Apply Azure Architecture Center and
  Well-Architected Framework patterns where practical.
- **Environment baseline**: Target a single standard Azure subscription (and, where relevant, a
  standard Microsoft 365 or Power Platform tenant) with default quotas. Avoid specialized hardware
  and region-specific services by default.
- **Priority technologies** (when applicable and GA): Microsoft Copilot Studio, Power Platform,
  Microsoft Fabric, Azure AI Foundry, Azure AI Search, Microsoft 365 Copilot extensibility,
  Dataverse, Azure Logic Apps, and Microsoft Entra.
- **Deliverable standard**: Each PoC produces the standard 13-section proof-of-concept deliverable
  and conforms to the Proof-of-Concept Reference Architecture Standard. Deviations require an
  architecture decision record (ADR) documenting rationale, risk, and an exit plan.
- **Source control**: Infrastructure, configuration, prompts, and deployment instructions MUST be
  version-controlled, with architecture and flows expressed as diagram-as-source where practical.

## Development Workflow & Quality Gates

- **Spec-driven flow**: Features follow the Spec Kit workflow — constitution → specify → clarify →
  plan → tasks → implement/converge → analyze.
- **Constitution gate**: Plans MUST pass the Constitution Check before Phase 0 research and be
  re-checked after design. Violations MUST be recorded in the plan's Complexity Tracking with
  justification or removed.
- **Custom-code justification**: Any custom code MUST be justified against Principle IV
  (Configuration Over Custom Code) before implementation.
- **Reproducibility review**: Before handoff, a second practitioner SHOULD validate the setup
  instructions and reproduce the primary demonstration using only the documented artifacts.
- **Completeness review**: Each PoC deliverable MUST pass a final review confirming that all
  required sections are present, internal references are consistent, evidence supports reported
  results, PoC-versus-production boundaries are stated, and no secrets or unapproved data are
  exposed.

## Governance

This constitution supersedes other practices for the design and delivery of proofs of concept within
this framework.

- **Amendments**: Proposed changes MUST include rationale and impact, be documented in this file,
  receive a version bump per the policy below, and be propagated to dependent templates and guidance.
- **Versioning policy**: This constitution uses semantic versioning. MAJOR increments for
  backward-incompatible governance or principle removals or redefinitions; MINOR for a new principle
  or section or materially expanded guidance; PATCH for clarifications, wording, and non-semantic
  refinements.
- **Compliance review**: Every spec, plan, and PoC deliverable MUST be checked against these
  principles. Reviewers MUST verify GA-first delivery, configuration over custom code,
  reproducibility, security and responsible AI, human oversight, observability, and the
  PoC-versus-production distinction. Complexity and deviations MUST be justified or corrected.
- **Runtime guidance**: Use the Spec Kit templates in `.specify/templates/` and the
  Proof-of-Concept Reference Architecture Standard in `docs/reference-architecture-standard.md` for
  day-to-day development guidance.

**Version**: 1.0.0 | **Ratified**: 2026-07-24 | **Last Amended**: 2026-07-24
