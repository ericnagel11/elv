"""Read and write experience profiles in Azure App Configuration using Entra ID.

Two stores model the governance boundary:

  production  the live experience the customer-facing application reads
  draft       the proposed experience an experience designer works on

Two stores are used rather than two labels because Azure does not support ABAC
role-assignment conditions for App Configuration, so a role cannot be limited to
a single label within a store. Microsoft guidance is to use a separate store for
each environment that requires different permissions.

Full-demo calls run under a persona's credential. An AccessDenied raised by
this module is a real Azure 403. Comparison restrictions raise OperationDisabled
locally, before any Azure request, and do not change the identity's Azure roles.
"""

import os
import re
from functools import lru_cache
from uuid import uuid4

from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting
from azure.core import MatchConditions
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceModifiedError, ResourceNotFoundError

import change_history
import rbac
from search_settings import validate_settings

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

COMPARISON_PROMPT_ASSETS = ("response:v1", "response:v2")
MAX_EDIT_VALUE_LENGTH = 2000

EDITABLE_KNOWLEDGE_KEYS = [
    "enabled",
    "index",
    "filter",
    "top_k",
    "query_mode",
    "citation_style",
]

COMPARISON_KNOWLEDGE_KEYS = EDITABLE_KNOWLEDGE_KEYS + [
    "title_field", "content_field", "url_field", "industry_field", "audience_field",
    "status_field", "effective_date_field", "state_field", "source_field", "search_fields",
]


def validate_knowledge_value(short_key: str, value: str) -> None:
    if short_key not in COMPARISON_KNOWLEDGE_KEYS:
        raise rbac.OperationDisabled("This knowledge setting is not editable.")
    if not isinstance(value, str) or "\x00" in value or len(value) > MAX_EDIT_VALUE_LENGTH:
        raise ValueError("Knowledge values must be text within the editor limit.")
    choices = {"enabled": {"true", "false"}, "query_mode": {"simple"},
               "citation_style": {"inline", "footnote", "none"}}
    if short_key in choices and value not in choices[short_key]:
        raise ValueError(f"knowledge:{short_key} must be one of: {', '.join(sorted(choices[short_key]))}.")
    if short_key == "index" and value not in rbac.approved_search_indexes():
        raise rbac.OperationDisabled("Choose an index approved in the VM runtime configuration.")
    if short_key == "top_k" and (not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 20):
        raise ValueError("knowledge:top_k must be an integer from 1 to 20.")
    if short_key.endswith("_field") or short_key == "search_fields":
        fields = value.split(",") if short_key == "search_fields" else [value]
        if any(field and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(/[A-Za-z][A-Za-z0-9_]*)*", field.strip()) for field in fields):
            raise ValueError("Use Search field names, not queries or expressions, for field mappings.")
        if short_key in {"title_field", "content_field", "search_fields"} and any(not field.strip() for field in fields):
            raise ValueError(f"knowledge:{short_key} requires a field name.")


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


@dataclass
class MutationResult:
    """Actual write outcomes, separately from best-effort history persistence."""

    operation_id: str = field(default_factory=lambda: str(uuid4()))
    changed_keys: list[str] = field(default_factory=list)
    unchanged_keys: list[str] = field(default_factory=list)
    audit_warnings: list[str] = field(default_factory=list)
    failed_key: str | None = None
    not_attempted: list[str] = field(default_factory=list)
    outcome: str = "success"


def _record(persona, **event) -> list[str]:
    # Even malformed history configuration must not turn a completed change
    # into a failed save or hide the original App Configuration exception.
    try:
        return change_history.record_event({**event, **rbac.actor_metadata(persona)})
    except Exception:
        return ["Change history was not recorded; the configuration outcome is unchanged."]


def _failure(exc, write_issued=False) -> tuple[str, str]:
    if isinstance(exc, CredentialError):
        return "failed", "authentication"
    if isinstance(exc, AccessDenied):
        return "denied", "authorization"
    status = getattr(exc, "status_code", None)
    if status in (409, 412):
        return "conflict", "conflict"
    if isinstance(exc, (ServiceRequestError, ServiceResponseError, TimeoutError)):
        return ("unknown" if write_issued else "failed"), "connection"
    if isinstance(exc, ValueError):
        return "failed", "validation"
    return ("unknown" if write_issued else "failed"), "service"


def store_endpoint(store: str) -> str:
    return os.environ.get(STORE_ENV[store], "")


def draft_configured() -> bool:
    return not rbac.comparison_mode() and bool(store_endpoint("draft"))


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
    allowed_prefixes = {EXPERIENCE_PREFIX}
    if rbac.rag_enabled():
        allowed_prefixes.add(KNOWLEDGE_PREFIX)
    if rbac.comparison_mode() and (
        store != "production" or persona != "app"
        or label not in PROFILE_LABELS or prefix not in allowed_prefixes
    ):
        raise rbac.OperationDisabled("Only approved production comparison settings are available.")

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


def _require_editable_setting(label: str, short_key: str, prefix: str = EXPERIENCE_PREFIX) -> None:
    if not rbac.config_editing_enabled():
        raise rbac.OperationDisabled("Live configuration editing is not enabled.")
    editable = EDITABLE_KEYS if prefix == EXPERIENCE_PREFIX else (
        COMPARISON_KNOWLEDGE_KEYS if prefix == KNOWLEDGE_PREFIX and rbac.rag_enabled() else ()
    )
    if label not in PROFILE_LABELS or short_key not in editable:
        raise rbac.OperationDisabled("Only enabled baseline/candidate settings can be edited.")


def load_editable_setting(label: str, short_key: str, prefix: str = EXPERIENCE_PREFIX) -> dict:
    """Read one existing live setting and its version under the runtime identity."""
    _require_editable_setting(label, short_key, prefix)

    def _read():
        try:
            setting = _client("production", "app").get_configuration_setting(
                key=f"{prefix}{short_key}", label=label
            )
        except ResourceNotFoundError:
            raise ConfigurationConflict("This setting is missing from the live profile.") from None
        if not setting.etag:
            raise ConfigurationConflict("The setting has no version; reload before editing.")
        return {"value": setting.value, "etag": setting.etag}

    return _guard(f"read the {label} {short_key} setting", "production", _read)


def update_experience_setting(label: str, short_key: str, value: str, expected_etag: str) -> dict:
    """Update an existing live value without overwriting another editor's version."""
    _require_editable_setting(label, short_key)
    if (not isinstance(value, str) or not value.strip() or "\x00" in value
            or len(value) > MAX_EDIT_VALUE_LENGTH):
        raise ValueError(f"The value must contain 1 to {MAX_EDIT_VALUE_LENGTH} characters without nulls.")
    if short_key == "prompt_asset" and value not in COMPARISON_PROMPT_ASSETS:
        raise ValueError("Choose response:v1 or response:v2 for the comparison prompt asset.")
    return _update_live_setting(label, short_key, value, expected_etag, EXPERIENCE_PREFIX)


def update_knowledge_setting(label: str, short_key: str, value: str, expected_etag: str) -> dict:
    """Update only approved retrieval settings; the Search index itself is unchanged."""
    _require_editable_setting(label, short_key, KNOWLEDGE_PREFIX)
    validate_knowledge_value(short_key, value)
    return _update_live_setting(label, short_key, value, expected_etag, KNOWLEDGE_PREFIX)


def _update_live_setting(label: str, short_key: str, value: str, expected_etag: str, prefix: str) -> dict:
    if not isinstance(expected_etag, str) or not expected_etag.strip() or expected_etag == "*":
        raise ValueError("Load the current setting version before saving.")

    def _update():
        client = _client("production", "app")
        try:
            current = client.get_configuration_setting(
                key=f"{prefix}{short_key}", label=label
            )
            if current.etag != expected_etag:
                raise ConfigurationConflict("This setting changed. Reload it before saving again.")
            if current.value == value:
                return {"value": current.value, "etag": current.etag}
            current.value = value
            saved = client.set_configuration_setting(
                current, etag=expected_etag, match_condition=MatchConditions.IfNotModified
            )
        except (ResourceModifiedError, ResourceNotFoundError):
            raise ConfigurationConflict("This setting changed or was removed. Reload it before saving again.") from None
        return {"value": saved.value, "etag": saved.etag}

    return _guard(f"update the live {label} {short_key} setting", "production", _update)


def set_value(short_key: str, value: str, store: str = "draft",
              label: str = DRAFT_LABEL, persona=None,
              prefix: str = EXPERIENCE_PREFIX, *, operation_id=None,
              operation="save", force=False) -> MutationResult:
    """Conditionally write one approved setting, then record app-only history.

    Reads before-values under the same persona, preserves metadata and uses its
    ETag to prevent a concurrent write invalidating the recorded delta. Ordinary
    no-ops do not write or create change events; permission probes explicitly
    force a same-value write. An exception retains its type and carries
    mutation_result for partial/warning display. There is no cross-service
    transaction: audit failure never retries or rolls back a configuration write.
    """
    key = f"{prefix}{short_key}"
    if key not in change_history.CONFIG_KEYS or store not in STORE_ENV or label not in PROFILE_LABELS:
        raise ValueError("Only the approved configuration keys, stores and profile labels are editable.")
    if not isinstance(value, str) or len(value) > change_history.MAX_VALUE_CHARS:
        raise ValueError("Configuration value must be text of at most 8192 characters.")
    if prefix == KNOWLEDGE_PREFIX:
        value = validate_settings({short_key: value})[short_key]
    result = MutationResult(operation_id=operation_id or str(uuid4()))
    before = after = None
    old_known = False
    write_issued = False
    try:
        client = _client(store, persona)

        def read_before():
            try:
                return client.get_configuration_setting(key=key, label=label)
            except ResourceNotFoundError:
                return None

        before = _guard(f"read {short_key} before update", store, read_before)
        old_known = True
        if force:
            # The permission probe must rewrite the *fresh* value, not an older
            # profile-cache value, and must never recreate a deleted setting.
            if before is None:
                raise ValueError("The permission-probe setting disappeared; refresh before checking again.")
            value = before.value
        if before is not None and before.value == value and not force:
            result.unchanged_keys.append(key)
            result.outcome = "unchanged"
            return result
        if before is not None and not before.etag:
            raise ValueError("The current setting has no ETag; refresh before editing.")
        setting = ConfigurationSetting(
            key=key, label=label, value=value,
            content_type=getattr(before, "content_type", None),
            tags=dict(getattr(before, "tags", None) or {}),
        )
        write_issued = True
        after = _guard(
            f"update {short_key}", store,
            lambda: client.add_configuration_setting(setting) if before is None else
            client.set_configuration_setting(
                setting, etag=before.etag, match_condition=MatchConditions.IfNotModified,
            ),
        )
        result.changed_keys.append(key)
    except Exception as exc:
        result.outcome, category = _failure(exc, write_issued)
        result.failed_key = key
        result.audit_warnings.extend(_record(
            persona, operation_id=result.operation_id, operation=operation, store=store,
            label=label, key=key, old_value=getattr(before, "value", None),
            new_value=value, old_value_known=old_known, old_etag=getattr(before, "etag", None),
            new_etag=None, outcome=result.outcome, error_category=category,
        ))
        exc.mutation_result = result
        raise
    result.audit_warnings.extend(_record(
        persona, operation_id=result.operation_id, operation=operation, store=store,
        label=label, key=key, old_value=getattr(before, "value", None), new_value=value,
        old_value_known=old_known, old_etag=getattr(before, "etag", None),
        new_etag=getattr(after, "etag", None), outcome="allowed" if force else "success",
        error_category=None,
    ))
    return result


def _write_batch(values: dict, store: str, persona, operation="save") -> MutationResult:
    """Stop at the first config failure and report partial application honestly."""
    result = MutationResult()
    keys = sorted(values)
    for position, key in enumerate(keys):
        prefix, short_key = key.split(":", 1)
        try:
            item = set_value(
                short_key, values[key], store=store, persona=persona, prefix=prefix + ":",
                operation_id=result.operation_id,
                operation="publish_key" if operation == "publish" else operation,
            )
        except Exception as exc:
            item = getattr(exc, "mutation_result", MutationResult())
            result.audit_warnings.extend(item.audit_warnings)
            result.failed_key = key
            result.not_attempted = keys[position + 1:]
            result.outcome = "partial" if result.changed_keys else item.outcome
            if operation == "publish":
                result.audit_warnings.extend(_record_summary(result, persona))
            exc.mutation_result = result
            raise
        result.changed_keys.extend(item.changed_keys)
        result.unchanged_keys.extend(item.unchanged_keys)
        result.audit_warnings.extend(item.audit_warnings)
    result.outcome = "success" if result.changed_keys else "unchanged"
    if operation == "publish":
        result.audit_warnings.extend(_record_summary(result, persona))
    return result


def _record_summary(result, persona) -> list[str]:
    return _record(
        persona, operation_id=result.operation_id, operation="publish_summary",
        store="production", label=DRAFT_LABEL, key=None, old_value=None, new_value=None,
        old_value_known=False, old_etag=None, new_etag=None, outcome=result.outcome,
        error_category=None, succeeded_keys=result.changed_keys,
        failed_key=result.failed_key, not_attempted=result.not_attempted,
    )


def save_knowledge(settings: dict, persona=None) -> MutationResult:
    """Validate the entire Search form before writing only changed draft keys."""
    normalized = validate_settings(settings)
    if any(len(value) > change_history.MAX_VALUE_CHARS for value in normalized.values()):
        raise ValueError("Search settings must not exceed 8192 characters per value.")
    return _write_batch({KNOWLEDGE_PREFIX + key: value for key, value in normalized.items()},
                        "draft", persona)


def publish_draft(persona=None) -> MutationResult:
    """Copy a captured draft into production candidate, with grouped history.

    Requires read on draft and write on production, so only the approver
    can change production. Writes are conditional per key, NOT an atomic batch.
    Validate all known values before the first write and preserve both prefixes.
    """
    result = MutationResult()
    try:
        values = {}
        for prefix in (EXPERIENCE_PREFIX, KNOWLEDGE_PREFIX):
            draft = load_profile(DRAFT_LABEL, store="draft", persona=persona, prefix=prefix)
            if any(prefix + key not in change_history.CONFIG_KEYS for key in draft):
                raise ValueError("Draft contains unsupported settings; review before publication.")
            if prefix == KNOWLEDGE_PREFIX and draft:
                normalized = validate_settings(draft)
                draft = {key: normalized[key] for key in draft}
            for key, value in draft.items():
                full_key = prefix + key
                if full_key not in change_history.CONFIG_KEYS:
                    raise ValueError("Draft contains unsupported settings; review before publication.")
                if not isinstance(value, str) or len(value) > change_history.MAX_VALUE_CHARS:
                    raise ValueError("Draft contains an invalid or oversized value.")
                values[full_key] = value
        if not values:
            raise ValueError("The draft profile is empty. Seed or save a draft before publishing.")
    except Exception as exc:
        result.outcome, _ = _failure(exc)
        result.audit_warnings.extend(_record_summary(result, persona))
        exc.mutation_result = result
        raise
    return _write_batch(values, "production", persona, operation="publish")


def _rewrite_first_value(store: str, label: str, persona) -> MutationResult:
    """Write a value back unchanged.

    The write still requires Data Owner, so it proves permission without
    altering any configuration.
    """
    rbac.require_full_demo("Permission testing")
    profile = load_profile(label, store=store, persona=persona)
    if not profile:
        raise RuntimeError(f"The {label} profile in the {store} store is empty.")
    short_key, value = sorted(profile.items())[0]
    return set_value(short_key, value, store=store, label=label, persona=persona,
                     operation="permission_probe", force=True)


def probe(persona: str) -> list:
    """Attempt each governed operation and report what Azure actually allowed."""
    rbac.require_full_demo("Permission testing")
    results = []

    def attempt(operation, store, action, write=False):
        warnings = []
        failure = None
        try:
            result = action()
            allowed, outcome, event_outcome = True, "Allowed", "allowed"
            if write:
                warnings.extend(result.audit_warnings)
        except Exception as exc:  # configuration gaps, not authorization
            failure = exc
            event_outcome, _ = _failure(exc)
            allowed = False if isinstance(exc, AccessDenied) else None
            outcome = ("Denied by Azure (403)" if allowed is False else
                       "Sign-in failed" if isinstance(exc, CredentialError) else
                       "Inconclusive: check configuration or connectivity")
            warnings.extend(getattr(exc, "mutation_result", MutationResult()).audit_warnings)
        # Internal writes already recorded themselves. Read probes or failure
        # before reaching set_value get one summary, without duplicate events.
        if not write or (failure is not None and not hasattr(failure, "mutation_result")):
            warnings.extend(_record(
                persona, operation_id=str(uuid4()), operation="permission_probe", store=store,
                label=DRAFT_LABEL, key=None, old_value=None, new_value=None,
                old_value_known=False, old_etag=None, new_etag=None,
                outcome=event_outcome, error_category=_failure(failure)[1] if failure else None,
            ))
        results.append({"operation": operation, "allowed": allowed,
                        "outcome": outcome, "audit_warnings": warnings})

    attempt("Read live experience", "production",
            lambda: load_profile(DRAFT_LABEL, "production", persona))
    attempt("Read draft experience", "draft",
            lambda: load_profile(DRAFT_LABEL, "draft", persona))
    attempt("Edit draft experience", "draft",
            lambda: _rewrite_first_value("draft", DRAFT_LABEL, persona), write=True)
    attempt("Publish to production", "production",
            lambda: _rewrite_first_value("production", DRAFT_LABEL, persona), write=True)
    return results


def endpoints_summary() -> dict:
    return {
        "App Configuration (production)": os.environ.get("AZURE_APPCONFIG_ENDPOINT", ""),
        "App Configuration (draft)": os.environ.get("AZURE_APPCONFIG_DRAFT_ENDPOINT", "not provisioned"),
        "Azure OpenAI": os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        "Deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
        "Azure AI Search": os.environ.get("AZURE_SEARCH_ENDPOINT", "not provisioned"),
    }