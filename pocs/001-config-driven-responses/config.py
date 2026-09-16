"""Read and write experience profiles in Azure App Configuration using Entra ID.

Two stores model the governance boundary:

  production  the live experience the customer-facing application reads
  draft       the proposed experience an experience designer works on

Two stores are used rather than two labels because Azure does not support ABAC
role-assignment conditions for App Configuration, so a role cannot be limited to
a single label within a store. Microsoft guidance is to use a separate store for
each environment that requires different permissions.

Every call here runs under a persona's credential. An AccessDenied raised by
this module is a real 403 returned by Azure, not an application-side check.
"""

import os
from functools import lru_cache

from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError

import rbac

EXPERIENCE_PREFIX = "experience:"

# Retrieval scope is configuration in exactly the same sense as tone is. The
# prefix is separate only so the two can be shown, and governed, independently.
KNOWLEDGE_PREFIX = "knowledge:"

PROFILE_LABELS = ["baseline", "candidate"]

# The proposal under development. The designer edits it in the draft store; the
# approver publishes it into the same label in the production store.
DRAFT_LABEL = "candidate"

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
    "prompt_asset",
]

EDITABLE_KNOWLEDGE_KEYS = [
    "enabled",
    "index",
    "filter",
    "top_k",
    "query_mode",
    "citation_style",
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
    """Return every key for a label under one prefix as a flat dict."""

    def _read():
        settings = _client(store, persona).list_configuration_settings(
            key_filter=f"{prefix}*",
            label_filter=label,
        )
        return {setting.key[len(prefix):]: setting.value for setting in settings}

    return _guard(f"read the {label} profile", store, _read)


def load_knowledge(label: str = DRAFT_LABEL, store: str = "production", persona=None) -> dict:
    """Return the knowledge:* retrieval scope for a label."""
    return load_profile(label, store, persona, prefix=KNOWLEDGE_PREFIX)


def set_value(short_key: str, value: str, store: str = "draft",
              label: str = DRAFT_LABEL, persona=None,
              prefix: str = EXPERIENCE_PREFIX):
    """Write one configuration key. Requires App Configuration Data Owner."""
    setting = ConfigurationSetting(
        key=f"{prefix}{short_key}", label=label, value=value
    )
    return _guard(
        f"update {short_key}",
        store,
        lambda: _client(store, persona).set_configuration_setting(setting),
    )


def publish_draft(persona=None) -> list:
    """Copy the draft profile into the production candidate profile.

    Requires read on draft and write on production, so only the approver
    succeeds. The designer is denied on the first write, leaving production
    untouched.
    """
    published = []
    found_any = False
    for prefix in (EXPERIENCE_PREFIX, KNOWLEDGE_PREFIX):
        draft = load_profile(DRAFT_LABEL, store="draft", persona=persona, prefix=prefix)
        if draft:
            found_any = True
        for short_key, value in sorted(draft.items()):
            set_value(short_key, value, store="production", label=DRAFT_LABEL,
                      persona=persona, prefix=prefix)
            published.append(f"{prefix}{short_key}")
    if not found_any:
        raise RuntimeError("The draft profile is empty. Run scripts/seed-config.ps1.")
    return published


def _rewrite_first_value(store: str, label: str, persona) -> None:
    """Write a value back unchanged.

    The write still requires Data Owner, so it proves permission without
    altering any configuration.
    """
    profile = load_profile(label, store=store, persona=persona)
    if not profile:
        raise RuntimeError(f"The {label} profile in the {store} store is empty.")
    short_key, value = sorted(profile.items())[0]
    set_value(short_key, value, store=store, label=label, persona=persona)


def probe(persona: str) -> list:
    """Attempt each governed operation and report what Azure actually allowed."""
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
                            "outcome": "Sign-in failed: check the configured Azure identity"})
        except Exception as exc:  # configuration gaps, not authorization
            results.append({"operation": operation, "allowed": None,
                            "outcome": f"Inconclusive: {exc}"})

    attempt("Read live experience",
            lambda: load_profile(DRAFT_LABEL, "production", persona))
    attempt("Read draft experience",
            lambda: load_profile(DRAFT_LABEL, "draft", persona))
    attempt("Edit draft experience",
            lambda: _rewrite_first_value("draft", DRAFT_LABEL, persona))
    attempt("Publish to production",
            lambda: _rewrite_first_value("production", DRAFT_LABEL, persona))
    return results


def endpoints_summary() -> dict:
    return {
        "App Configuration (production)": os.environ.get("AZURE_APPCONFIG_ENDPOINT", ""),
        "App Configuration (draft)": os.environ.get("AZURE_APPCONFIG_DRAFT_ENDPOINT", "not provisioned"),
        "Azure OpenAI": os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        "Deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
        "Azure AI Search": os.environ.get("AZURE_SEARCH_ENDPOINT", "not provisioned"),
    }
