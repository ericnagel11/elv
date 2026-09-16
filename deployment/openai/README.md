# Azure OpenAI: one-deployment inference check

**Status (2026-09-14):** The customer ran the probe on the approved Windows VM
and supplied `INFERENCE_SUCCEEDED` for the reported GPT-4o deployment, using the
same explicitly selected managed identity that passed the App Configuration
read check. This establishes connectivity and permission for this synthetic
chat request, not the exact RBAC assignment, model snapshot/version, quota
headroom, Python SDK compatibility or full PoC readiness. No Azure resources,
deployments, role assignments or App Configuration keys were changed.

## What running this check authorizes

[check-inference.ps1](check-inference.ps1) uses Windows PowerShell 5.1/7 and the
installed Azure CLI. It requires no Python, PoC dependencies, keys or secrets.
It submits **one synthetic chat-completions request**, with the prompt
`Reply with OK.`, one completion and a 16-token output limit. This consumes
model quota and can incur a small model-usage charge. It is **not** a read-only
metadata probe. The script contains no inference retry loop or load test.

It does not create/delete resources or deployments, change RBAC/network settings,
seed App Configuration, upload files to Azure or use customer documents. Azure
may retain service-side request/audit records under the customer's existing
policies. Success verifies this request, not response quality, full PoC operation,
the deployed model snapshot, or the Python SDK dependencies.

## Before running

- Use the approved **customer Azure Windows VM**, not the operator workstation.
  The supplied user-assigned managed identity must be attached and authorized for
  this OpenAI resource. All trusted VM users can potentially use its identities.
- The identity needs OpenAI inference permission, normally **Cognitive Services
  OpenAI User** scoped to the approved account. App Configuration Data Owner does
  not grant OpenAI access. Do not broaden permissions automatically on failure.
- The VM needs IMDS and HTTPS access to the OpenAI account using the approved
  private DNS/proxy/CA configuration. Leave public access and TLS verification
  unchanged. Existing proxy bypasses are preserved and IMDS/loopback appended.
- Use the account endpoint, not a Foundry project URL; use the **deployment
  name**, not the model name. This probe targets commercial Azure OpenAI GPT-4o
  chat deployments with API version `2024-10-21` and `max_tokens`.
- Deliver the standalone script through the approved source-transfer route.
  Follow script-signing policy; do not bypass execution policy. Run with `&`
  from an already-open PowerShell window, not by dot-sourcing or right-clicking.

From the repository root on the VM, substitute the nonsecret values:

```powershell
& .\deployment\openai\check-inference.ps1 -Endpoint 'https://YOUR-ACCOUNT.openai.azure.com/' -Deployment 'YOUR-DEPLOYMENT' -ClientId 'YOUR-UAMI-CLIENT-UUID' -ApprovedAzureHost -AllowInference
```

`-ApprovedAzureHost` acknowledges the execution location/identity approval;
`-AllowInference` authorizes the synthetic request and associated usage. Omitting
either stops before Azure CLI is called. The probe establishes its own explicit
managed-identity login; the earlier App Configuration check deliberately did not
leave a CLI session signed in.

The CLI handles the Cognitive Services audience token internally. Tokens are
never passed through PowerShell variables, printed, placed in command arguments
or included in the request-body file. Before login, a fresh temporary CLI cache
parent is restricted to the current Windows identity and SYSTEM. VM administrators
still control the host. Caller environment settings are restored and private
cache/body/error files removed in `finally`. A crash or uncatchable termination
can prevent cleanup; honor the customer's token-cache handling policy.

## Results

Results are console-only. Share the fixed summary, not raw CLI diagnostics or
token/cache files. No generated model text is displayed.

| Exit | Meaning |
| --- | --- |
| 0 | `INFERENCE_SUCCEEDED`: the selected identity completed the synthetic request. |
| 2 | Missing host/cost approval, invalid input, missing CLI or local probe error. |
| 3 | Identity login failed; no inference request was made. |
| 4 | Inference request failed; use the reported diagnostic category. |
| 5 | Temporary private-cache cleanup failed; authorized local cleanup is needed. |

- **403:** check OpenAI RBAC and resource network restrictions independently.
- **401:** check identity/tenant and the Cognitive Services token audience.
- **404:** check endpoint, deployment name/availability and API version. Do not
  assume a new deployment is needed.
- **429:** check quota/rate limits with the owner, rather than retrying repeatedly.
- **DNS/TLS/timeout:** check approved network/proxy/CA configuration, not roles.
- **400:** check model/API/request compatibility and service policy.

## Offline validation

These tests use only a harmless local batch fixture, not real Azure CLI, IMDS,
tokens or model requests. No Pester or Python installation is needed:

```powershell
& .\deployment\appconfig\tests\test-check-access.ps1
& .\deployment\appconfig\tests\test-check-access.ps1 -ProbePath (Join-Path $PWD 'deployment\openai\check-inference.ps1')
& .\deployment\openai\tests\test-check-inference.ps1
```

They cover native exit-code handling, approvals before CLI activity, endpoint and
deployment validation, fixed payload, explicit identity/audience, success and
failure categories, suppressed output, environment restoration and cleanup.
Passing offline tests is not evidence of actual OpenAI access from the VM.

On 2026-09-14 the offline suites passed in local Windows PowerShell 5.1, including
the native exit-code regressions for both probes and the mocked OpenAI request
paths. Editor diagnostics reported no errors. Separately, the customer supplied
the successful live inference summary noted above. No Azure/model calls were
made by the offline tests or by the assistant. PowerShell 7 execution remains
unverified; the customer's exact PowerShell version has not been recorded.

References: [Azure CLI REST requests](https://learn.microsoft.com/cli/azure/reference-index#az-rest),
[Azure OpenAI API reference](https://learn.microsoft.com/azure/ai-foundry/openai/reference),
[Azure OpenAI roles](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/role-based-access-control).