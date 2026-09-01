# Data Model: Standard Proof-of-Concept Template

## Proof-of-Concept Scenario

Represents one independently configured and validated business scenario.

**Fields**: scenario ID, title, business objective, owner, stakeholders, priority, scope, exclusions, assumptions, environment, status, start date, validation date, outcome.

**Relationships**: Has many Azure resources, Microsoft 365 capabilities, configuration steps, sample-data assets, validation checkpoints, result records, and risks or recommendations.

**Validation rules**:
- Must map to all 13 required deliverable sections.
- Must define objective success criteria before execution.
- Must identify accountable owners and required approvals.
- Must retain explicit not-applicable explanations.

## Azure Resource

**Fields**: resource type, service name, purpose, subscription, resource group, region, SKU or tier, networking mode, identity, tags, estimated cost, lifecycle owner, cleanup action.

**Validation rules**:
- Required resources must identify permissions and provisioning checkpoints.
- Secret values must never be recorded.
- Regional, quota, and licensing dependencies must be explicit.

## Microsoft 365 Capability

**Fields**: workload, capability, tenant, license, admin role, user role, configuration location, dependency, policy impact, validation method.

**Validation rules**:
- Required licenses, roles, consent, and tenant settings must be stated.
- Changes to tenant-wide settings require an owner, approval, and rollback instruction.

## Configuration Step

**Fields**: sequence, action, portal or tool, responsible role, prerequisites, permissions, input, expected checkpoint, validation action, recovery guidance, evidence reference.

**Validation rules**:
- Steps must be executable in order without undocumented decisions.
- Every major step must have an observable checkpoint.

## Sample Data Asset

**Fields**: name, purpose, source, classification, format, schema, volume, generation or sanitization method, load instructions, expected records, handling constraints, retention, cleanup.

**Validation rules**:
- Synthetic or sanitized data is the default.
- Confidential, personal, regulated, or customer-owned data requires explicit approval and controls.

## Validation Checkpoint

**Fields**: checkpoint ID, prerequisite, action, expected observation, evidence, pass criteria, actual observation, status, variance, corrective action, validator.

**State transitions**: Not Run -> Passed | Failed | Blocked; Failed or Blocked -> Retest -> Passed | Failed.

## Result Record

**Fields**: success criterion, expected result, actual result, evidence, variance, likely cause, status, decision impact.

## Risk and Recommendation

**Fields**: category, description, likelihood, impact, mitigation, residual risk, owner, next action, target date, production relevance.
