"""Read and write market configuration in Azure App Configuration using Entra ID.

Two stores model the governance boundary, exactly as in proof of concept 001:

  production  the live configuration the customer-facing application reads
  draft       the proposed configuration a designer or market owner works on

Two stores are used rather than two labels because Azure does not support ABAC
role-assignment conditions for App Configuration, so a role cannot be limited to
a single label within a store. That limit matters more here than it did in 001:
markets *are* labels, so Azure cannot express "this team may change only the
de-DE market". The governance tab says so plainly and names the compensating
control rather than implying the platform enforces it.

Three prefixes make up a market profile:

  experience:  how the assistant speaks (tone, formality, structure)
  market:      what is true about the market (language, jurisdiction, notices)
  knowledge:   what the assistant may draw on (filter, index, certification gate)

Every call here runs under a persona's credential. An AccessDenied raised by
this module is a real 403 returned by Azure, not an application-side check.
"""

import os
from functools import lru_cache

from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError

import rbac

EXPERIENCE_PREFIX = "experience:"

# New in this proof of concept. Holds the facts about a market that are neither
# voice nor retrieval: which language, which jurisdiction, which notices apply,
# where a handoff goes.
MARKET_PREFIX = "market:"

KNOWLEDGE_PREFIX = "knowledge:"

STORE_ENV = {
    "production": "AZURE_APPCONFIG_ENDPOINT",
    "draft": "AZURE_APPCONFIG_DRAFT_ENDPOINT",
}

EDITABLE_KEYS = [
    "tone",
    "verbosity",
    "reading_level",
    "response_structure",
    "persona",
    "formality",
    "prompt_asset",
]

EDITABLE_KNOWLEDGE_KEYS = [
    "enabled",
    "index",
    "filter",
    "top_k",
    "query_mode",
    "citation_style",
    "translation_gate",
]


class AccessDenied(Exception):
    """Azure RBAC refused the operation for the acting identity."""

    def __init__(self, operation: str, store: str, detail: str = ""):
        self.operation = operation
        self.store = store
        self.detail = detail
        super().__init__(f"Azure denied '{operation}' on the {store} store.")


class CredentialError(Exception):
    """The acting identity could not sign in at all.

    This is distinct from AccessDenied. A stale or rotated client secret fails
    every operation, which looks like a permission problem but is not one.
    """

    def __init__(self, store: str, detail: str = ""):
        self.store = store
        self.detail = detail
        super().__init__("Could not sign in as this identity.")


def store_endpoint(store: str) -> str:
    return os.environ.get(STORE_ENV[store], "")


def draft_configured() -> bool:
    return bool(store_endpoint("draft"))


@lru_cache(maxsize=16)
def _client(store: str, persona) -> AzureAppConfigurationClient:
    endpoint = store_endpoint(store)
    if not endpoint:
        raise RuntimeError(
            f"No endpoint for the {store} store. Run scripts/setup-governance.ps1."
        )
    return AzureAppConfigurationClient(
        base_url=endpoint, credential=rbac.credential_for(persona)
    )


def _guard(operation: str, store: str, action):
    try:
        return action()
    except ClientAuthenticationError as exc:
        raise CredentialError(store, str(exc)) from exc
    except HttpResponseError as exc:
        # 401 means the identity could not be authenticated; 403 means it was
        # authenticated and then refused. Conflating them hides stale secrets.
        if exc.status_code == 401:
            raise CredentialError(store, (exc.message or "").strip() or "Unauthorized") from exc
        if exc.status_code == 403:
            # A denied response often has an empty or non-JSON body, so fall
            # back to the status code rather than showing a blank reason.
            detail = (exc.message or "").strip() or "Forbidden"
            raise AccessDenied(operation, store, f"HTTP 403: {detail}") from exc
        raise


def load_profile(label: str, store: str = "production", persona=None,
                 prefix: str = EXPERIENCE_PREFIX) -> dict:
    """Return every key for one label under one prefix as a flat dict.

    This reads a single layer. Composing the layers into a market profile is
    market.resolve()'s job, because that is where provenance is tracked.
    """

    def _read():
        settings = _client(store, persona).list_configuration_settings(
            key_filter=f"{prefix}*",
            label_filter=label,
        )
        return {setting.key[len(prefix):]: setting.value for setting in settings}

    return _guard(f"read the {label} layer", store, _read)


def set_value(short_key: str, value: str, label: str, store: str = "draft",
              persona=None, prefix: str = EXPERIENCE_PREFIX):
    """Write one configuration key. Requires App Configuration Data Owner."""
    setting = ConfigurationSetting(
        key=f"{prefix}{short_key}", label=label, value=value
    )
    return _guard(
        f"update {short_key} on the {label} layer",
        store,
        lambda: _client(store, persona).set_configuration_setting(setting),
    )


def delete_value(short_key: str, label: str, store: str = "draft", persona=None,
                 prefix: str = EXPERIENCE_PREFIX):
    """Remove an override so the key falls back to the layer beneath it.

    Deleting a market override is how a market rejoins the global default, and
    it is a governed act like any other write.
    """
    return _guard(
        f"delete {short_key} from the {label} layer",
        store,
        lambda: _client(store, persona).delete_configuration_setting(
            key=f"{prefix}{short_key}", label=label
        ),
    )


def publish_layer(label: str, persona=None, prefixes=None) -> list:
    """Copy one layer from the draft store into the production store.

    Publishing is per layer because a layer is what a reviewer approves. A
    market owner proposes changes to the `de-DE` layer; an approver publishes
    that layer without touching `baseline` or any other market.

    Requires read on draft and write on production, so only the approver
    succeeds. Anyone else is denied on the first write, leaving production
    untouched.
    """
    published = []
    found_any = False
    for prefix in (prefixes or (EXPERIENCE_PREFIX, MARKET_PREFIX, KNOWLEDGE_PREFIX)):
        draft = load_profile(label, store="draft", persona=persona, prefix=prefix)
        if draft:
            found_any = True
        for short_key, value in sorted(draft.items()):
            set_value(short_key, value, label=label, store="production",
                      persona=persona, prefix=prefix)
            published.append(f"{prefix}{short_key}")
    if not found_any:
        raise RuntimeError(
            f"The '{label}' layer is empty in the draft store. Run scripts/seed-config.ps1."
        )
    return published


def pending_changes(label: str, persona=None) -> list:
    """What the draft store would change in production if this layer published."""
    rows = []
    for prefix in (EXPERIENCE_PREFIX, MARKET_PREFIX, KNOWLEDGE_PREFIX):
        draft = load_profile(label, store="draft", persona=persona, prefix=prefix)
        live = load_profile(label, store="production", persona=persona, prefix=prefix)
        for short_key, value in sorted(draft.items()):
            if live.get(short_key) != value:
                rows.append({
                    "setting": f"{prefix}{short_key}",
                    "live in production": live.get(short_key, "(not set)"),
                    "waiting in draft": value,
                })
    return rows


def _rewrite_first_value(store: str, label: str, persona) -> None:
    """Write a value back unchanged.

    The write still requires Data Owner, so it proves permission without
    altering any configuration.
    """
    for prefix in (MARKET_PREFIX, EXPERIENCE_PREFIX, KNOWLEDGE_PREFIX):
        profile = load_profile(label, store=store, persona=persona, prefix=prefix)
        if profile:
            short_key, value = sorted(profile.items())[0]
            set_value(short_key, value, label=label, store=store, persona=persona,
                      prefix=prefix)
            return
    raise RuntimeError(f"The '{label}' layer in the {store} store is empty.")


def probe(persona: str, label: str) -> list:
    """Attempt each governed operation against one layer and report the outcome.

    The label matters: running this for `de-DE` and then for `es-MX` returns the
    same answers for every identity, which is the point. Azure cannot scope a
    data-plane role to a label, so an identity that may edit one market may edit
    them all.
    """
    results = []

    def attempt(operation, action):
        try:
            action()
            results.append({"operation": operation, "allowed": True,
                            "outcome": "Allowed"})
        except AccessDenied:
            results.append({"operation": operation, "allowed": False,
                            "outcome": "Denied by Azure (403)"})
        except CredentialError:
            results.append({"operation": operation, "allowed": None,
                            "outcome": "Sign-in failed: the client secret looks stale"})
        except Exception as exc:  # configuration gaps, not authorization
            results.append({"operation": operation, "allowed": None,
                            "outcome": f"Inconclusive: {exc}"})

    attempt(f"Read live '{label}' layer",
            lambda: load_profile(label, "production", persona, prefix=MARKET_PREFIX))
    attempt(f"Read draft '{label}' layer",
            lambda: load_profile(label, "draft", persona, prefix=MARKET_PREFIX))
    attempt(f"Edit draft '{label}' layer",
            lambda: _rewrite_first_value("draft", label, persona))
    attempt(f"Publish '{label}' to production",
            lambda: _rewrite_first_value("production", label, persona))
    return results


def endpoints_summary() -> dict:
    return {
        "App Configuration (production)": os.environ.get("AZURE_APPCONFIG_ENDPOINT", ""),
        "App Configuration (draft)": os.environ.get("AZURE_APPCONFIG_DRAFT_ENDPOINT", "not provisioned"),
        "Azure OpenAI": os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        "Deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
        "Azure AI Search": os.environ.get("AZURE_SEARCH_ENDPOINT", "not provisioned"),
        "Azure AI Language": os.environ.get("AZURE_LANGUAGE_ENDPOINT", "not provisioned"),
    }
