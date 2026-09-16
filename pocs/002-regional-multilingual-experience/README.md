# Regional and Multilingual Experience PoC

Serving three markets from one application, where the language, the register,
the content, and the required notices are all configuration rather than code.

This is proof of concept 002. It builds directly on
[001-config-driven-responses](../001-config-driven-responses/README.md), which
established that an assistant's voice and knowledge can be governed configuration.
That claim is assumed here and not re-demonstrated. What is added is the second
axis: **market**.

The narrative form is whitepaper section 1.3 in
[docs/configurable-conversational-experience.md](../../docs/configurable-conversational-experience.md).
The testable specification is
[specs/002-regional-multilingual-experience](../../specs/002-regional-multilingual-experience/spec.md).

Working markets: **en-US**, **es-MX**, **de-DE**.

## What it demonstrates

1. **A market is a sparse set of overrides, and inheritance is visible.**
   Configuration resolves through three layers (`baseline`, then `de-DE`, then
   `de-DE-candidate`), and every resolved value reports which layer supplied it.
   `en-US` overrides four keys and inherits everything else.

2. **Regionality is three problems, not one.** Language, market rules, and
   jurisdiction have different owners and different failure modes. Ask all three
   markets the same returns question: the answers differ in language, in
   register, and in *substance*, because a German customer's statutory
   withdrawal right is not the American commercial return window. Translation
   alone would have carried the wrong fact across the border in perfect grammar.

3. **Certification is a gate, not a label.** A document answers in a market only
   when the human assurance behind its text meets what that market requires.
   `knowledge:translation_gate` is that requirement, and moving it is an
   approved, audited configuration change.

4. **Required notices reach the customer verbatim.** Disclosure text is appended
   after generation and never passes through the model, so it cannot be
   paraphrased, shortened, or translated into a compliance defect.

5. **Translation drift is detectable.** A certified translation stays certified
   after its source is revised. Recording the source version at translation time
   turns that from an inspection into a report.

6. **Azure cannot enforce per-market permissions, and the app says so.** Because
   a market *is* a label, and role assignment conditions do not extend to App
   Configuration, the market owner persona holds exactly the same permissions as
   the global designer. The governance tab demonstrates the limit and names the
   compensating controls rather than implying the platform closes the gap.

## How the second axis works

Configuration is read from three labels in order, most specific last. A layer
that does not mention a key leaves the inherited value in place.

| Layer | Label | Holds |
|---|---|---|
| Global default | `baseline` | Every key |
| Market override | `de-DE` | Only the keys that differ for this market |
| Experiment override | `de-DE-candidate` | Only the keys under test |

Prompt assets resolve through a matching chain, so a market file exists only
where the market must differ:

| Market | Resolves to | Why |
|---|---|---|
| `de-DE` | `response.v3.de.prompty` | Language level, shared with any future de-AT or de-CH |
| `es-MX` | `response.v3.es-MX.prompty` | Market level, because Mexican service Spanish uses *usted* differently from peninsular Spanish |
| `en-US` | `response.v3.prompty` | Neutral fallback |

Retrieval uses one index per language behind an alias, because the Azure AI
Search `analyzer` property is set on a field and fixed at index creation. There
is no per-document analyzer, so German decompounding and Spanish lemmatization
need an index (or a field) per language.

## Prerequisites

### Red Hat VM / existing Azure services

Use the shared [Red Hat hosting runbook](../../deployment/redhat/README.md).
It runs both PoCs headlessly using private systemd services, separate Python
environments and explicit managed identities. Run applications and tests on the
VM only; use a workstation browser through the approved SSH tunnel.

**Do not use the provisioning/teardown steps below against existing shared Azure
resources.** Those steps describe the original disposable development setup and
can overwrite settings or delete services. VM deployment requires Search,
Language and audit readiness for the full demo; target VM verification is pending.

### Original disposable development environment

- Azure CLI, signed in to a subscription where you can create Azure OpenAI.
- Python 3.10 or later.
- To create service principals: rights to create Entra ID app registrations,
  for example the Application Developer role.

## Setup

```powershell
# 1. Provision resource group, App Configuration, and Azure OpenAI; write .env.
pwsh scripts/setup.ps1

# 2. Add the governance layer: draft store, Log Analytics, five service
#    principals with different roles.
pwsh scripts/setup-governance.ps1 -ProductionStore <name>-appcfg

# 3. Seed the global default layer and the three market layers into both stores.
pwsh scripts/seed-config.ps1 -AppConfigName <name>-appcfg -DraftAppConfigName <name>-appcfg-draft

# 4. Add the knowledge layer: storage, Azure AI Search, and one index, alias,
#    data source and indexer per language.
pwsh scripts/setup-knowledge.ps1 -ProductionStore <name>-appcfg

# 5. Optional: add the language-adherence guardrail.
pwsh scripts/setup-language.ps1 -ProductionStore <name>-appcfg
```

Steps 4 and 5 are optional. Without them the app runs and reports those layers as
unprovisioned rather than failing.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Try the demo

**Market comparison tab** is the one to show first. Ask the same returns question
across all three markets. Note that the substance differs, not just the wording,
and that the summary table underneath attributes every difference to a
configuration value or a resolved asset.

**Market experience tab.** Pick `de-DE`, ask a question, then open *Resolved
configuration, and which layer supplied it*. Most values come from `baseline`.
The market layer supplies the formality, the notice, the glossary, the index, and
the filter. Open *Prompt asset resolution* to see the chain that was tried.

**Certification gate tab.** With `de-DE` selected, compare the configured gate
against `machine_allowed`. The right-hand column admits documents that the market
has not certified, and the app flags them. Nothing about the content, the index,
the prompt asset, or the code changed between the two columns. Then scroll to the
drift report: one German document is certified against version 2 of a source that
is now at version 3.

**Inheritance tab.** Choose `experience` and `tone`, then show the blast radius.
Two markets inherit that key and would receive a global change without a market
reviewer seeing it. `es-MX` and `de-DE` override `formality`, so choosing that
key instead shows the opposite.

**Governance tab.** Select the market owner persona, run the permission check for
`de-DE`, then switch the market to `es-MX` in the sidebar and run it again. The
answers are identical, which is the RBAC limitation made visible rather than
described. Then act as the designer, edit the draft `de-DE` layer, try to
publish (denied), switch to the approver, and publish.

**Audit tab.** *Gate and notice changes* answers the question a compliance
reviewer will actually ask: who decided that less-reviewed content could answer
customers in this market, and when.

## Security notes

- VM mode uses explicit managed identities, skips dotenv/persona-secret files,
  and uses resource-context audit requests. Every presenter can select every
  persona; this is not user authentication or isolation between VM processes.
- Runtime Azure calls use Entra ID. The original Free-tier Search setup can use
  a storage account key for its indexer; the VM hosting installer does not run it.
- `roles.local.json` holds client secrets and is excluded by `.gitignore`.
  In the original non-VM mode, client secrets are a proof-of-concept shortcut so one process can act as five
  identities. Production would use managed identity or user sign-in.
- All content is synthetic. The German and Spanish policy documents are written
  for a demonstration. They are illustrative of the workflow and are not legal
  advice or a compliant notice for any real service.
- Disclosure text never passes through the model, which removes an entire class
  of compliance risk from the non-deterministic part of the system.

## Cost and teardown

App Configuration runs on the Free tier, the draft store on Developer, Azure AI
Search on Free, and Azure AI Language on F0. Three languages is exactly the Free
search tier's limit of three indexes, three indexers, and three data sources. The
model is billed per token, so a demonstration costs cents.

```powershell
pwsh scripts/teardown.ps1
```

Teardown deletes the five app registrations before the resource group, because
registrations live in Entra ID and would otherwise be orphaned.

## Not included (production evolution)

- **Fallback when no content meets a market's gate.** The app declines and offers
  the market's escalation path. A production design would make this a governed
  per-market choice covering refusal, handoff, answering from the source language
  with a notice, and machine translation with a notice. Whitepaper section 1.3
  describes the options; this proof of concept demonstrates the certified path
  only, deliberately.
- **Per-market delegation.** Requires per-locale code ownership, a gatekeeper
  component, or a store per market cohort. The app names these and implements
  none of them.
- **Measured experiments.** The `de-DE-candidate` layer shows the third
  resolution layer exists. Running a real per-market A/B test needs one variant
  flag per market, telemetry carrying the market alongside the variant, and
  enough traffic per market to conclude. Readability must be measured with a
  formula appropriate to each language and compared only against that market's
  own baseline, never ranked across markets.
- **Data residency, formatting conventions, and right-to-left scripts.** Real
  regional concerns, separate problems, out of scope here.
- **Golden-set evaluation per market**, which is where claims such as "German
  instructions improve register adherence" should be tested rather than assumed.
