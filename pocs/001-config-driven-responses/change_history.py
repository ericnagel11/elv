"""Best-effort, application-only configuration history in a dedicated container.

No provisioning, account keys, SAS, Log Analytics queries, background work, or
local fallback. Blob create-only writes are not WORM or a transaction with App
Configuration: a process crash or failed upload can leave a gap. Config values
are intentionally recorded; operators must not put secrets or personal data in
the approved experience/knowledge settings. Arbitrary error messages,
credentials, token claims, and extra caller metadata are never serialized.

Callers select the default 24-hour window and pass timezone-aware datetimes to
load_events (inclusive start, exclusive end). Limits are conservative: partial
results are NOT necessarily the newest rows of an unscanned day. Time budgets
are checked between synchronous SDK calls; socket/service timeouts and bounded
retries apply per request, not as a hard deadline on credential acquisition.
"""

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import io
import json
import os
import re
from time import monotonic
import unicodedata
from uuid import UUID, uuid4

from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.storage.blob import ContainerClient, ContentSettings, ExponentialRetry

import rbac

MAX_HISTORY_DAYS = 30
MAX_EVENTS = 500
MAX_VALUE_CHARS = 8192
MAX_BLOB_BYTES = 128 * 1024
MAX_LISTED_BLOBS = 1000
MAX_LIST_PAGES = 64
MAX_DOWNLOADS = 1000
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
MAX_READ_SECONDS = 30
LIST_PAGE_SIZE = 100
REQUEST_TIMEOUT = 5

# Deliberately independent of config.py, which calls this module on mutations.
CONFIG_KEYS = frozenset({
    "experience:tone", "experience:verbosity", "experience:reading_level",
    "experience:response_structure", "experience:persona", "experience:prompt_asset",
    "knowledge:enabled", "knowledge:index", "knowledge:filter", "knowledge:top_k",
    "knowledge:query_mode", "knowledge:citation_style",
    "knowledge:title_field", "knowledge:content_field", "knowledge:url_field",
    "knowledge:industry_field", "knowledge:audience_field", "knowledge:status_field",
    "knowledge:effective_date_field", "knowledge:state_field", "knowledge:source_field",
    "knowledge:search_fields",
})
OPERATIONS = frozenset({
    "save", "set_value", "update", "publish", "publish_draft", "publish_key",
    "publish_summary", "permission_probe",
})
OUTCOMES = frozenset({
    "success", "succeeded", "failed", "failure", "denied", "allowed", "conflict",
    "unknown", "partial", "noop", "unchanged", "skipped", "not_attempted",
})
ERROR_CATEGORIES = frozenset({
    "authentication", "authorization", "credential", "access_denied", "forbidden",
    "conflict", "not_found", "timeout", "connection", "service", "unavailable",
    "validation", "configuration", "unknown", "other",
})
CSV_COLUMNS = (
    "schema_version", "event_id", "operation_id", "timestamp", "source",
    "operation", "store", "label", "key", "old_value", "new_value",
    "old_value_known", "old_etag", "new_etag", "outcome", "error_category",
    "actor_persona", "actor_client_id", "succeeded_keys", "failed_key", "not_attempted",
)
_ACCOUNT_URL = re.compile(r"https://[a-z0-9]{3,24}\.blob\.core\.windows\.net/?")
_CONTAINER = re.compile(r"(?=.{3,63}\Z)[a-z0-9]+(?:-[a-z0-9]+)*")
_BLOB_NAME = re.compile(
    r"\d{4}-\d{2}-\d{2}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}\.json"
)
_LIMIT_WARNING = (
    "History is partial: a row, listing, download, byte or time limit was reached. "
    "These rows are not guaranteed to be the newest across the entire selection."
)
_SKIP_WARNING = "History is partial: invalid, oversized or no-longer-available event files were skipped."


@dataclass
class HistoryPage:
    events: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False


class HistoryUnavailable(RuntimeError):
    """History could not be read; messages never contain provider exception text."""


def backend() -> str:
    """Blob by default; only explicit loganalytics opts into resource-log history."""
    value = os.environ.get("ELV_AUDIT_BACKEND", "blob").strip().lower()
    if value not in {"blob", "loganalytics"}:
        raise ValueError("ELV_AUDIT_BACKEND must be blob or loganalytics.")
    return value


def _settings() -> tuple[str, str]:
    account = os.environ.get("ELV_AUDIT_BLOB_ACCOUNT_URL", "").strip()
    container = os.environ.get("ELV_AUDIT_BLOB_CONTAINER", "").strip()
    if not _ACCOUNT_URL.fullmatch(account) or not _CONTAINER.fullmatch(container):
        raise ValueError("A commercial HTTPS Blob account URL and dedicated container name are required.")
    return account.rstrip("/"), container


def _uuid(value) -> str:
    if type(value) is not str or len(value) > 64:
        raise ValueError("An event identifier must be a UUID.")
    identity = UUID(value)
    if not identity.int:
        raise ValueError("An event identifier must be nonzero.")
    return str(identity)


def _text(value, limit: int):
    if value is None:
        return None
    if type(value) is not str or len(value) > limit:
        raise ValueError("An event field is invalid or too large.")
    # JSON can contain escaped lone surrogates even when the blob bytes are
    # valid UTF-8. Reject those here rather than breaking the display/CSV later.
    value.encode("utf-8")
    return value


def _choice(value, choices):
    if type(value) is not str or value not in choices:
        raise ValueError("An event field is not supported.")
    return value


def _key(value):
    return None if value is None else _choice(value, CONFIG_KEYS)


def _key_list(value) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) > len(CONFIG_KEYS):
        raise ValueError("An event summary is invalid or too large.")
    return [_choice(key, CONFIG_KEYS) for key in value]


def _base_event(event: dict) -> dict:
    """Construct an allowlisted schema, never copying an input dictionary wholesale."""
    if type(event) is not dict:
        raise ValueError("An event must be a dictionary.")
    result = {
        "operation_id": _uuid(event.get("operation_id")),
        "operation": _choice(event.get("operation"), OPERATIONS),
        "store": _choice(event.get("store"), {"production", "draft"}),
        "label": _text(event.get("label"), 128),
        "key": _key(event.get("key")),
        "old_value": _text(event.get("old_value"), MAX_VALUE_CHARS),
        "new_value": _text(event.get("new_value"), MAX_VALUE_CHARS),
        "old_value_known": event.get("old_value_known"),
        "old_etag": _text(event.get("old_etag"), 256),
        "new_etag": _text(event.get("new_etag"), 256),
        "outcome": _choice(event.get("outcome"), OUTCOMES),
    }
    if type(result["old_value_known"]) is not bool:
        raise ValueError("old_value_known must be explicit.")
    if not result["old_value_known"] and result["old_value"] is not None:
        raise ValueError("An unknown before-value cannot be supplied as known content.")
    if result["key"] is None and any(result[name] is not None for name in ("old_value", "new_value")):
        raise ValueError("Only approved configuration keys can carry values.")
    # Never stringify an exception supplied in place of a bounded category.
    category = event.get("error_category")
    result["error_category"] = (
        None if category is None or category == "" else
        category if type(category) is str and category in ERROR_CATEGORIES else "unknown"
    )
    persona = event.get("actor_persona")
    result["actor_persona"] = persona if type(persona) is str and persona in rbac.PERSONAS else None
    result["actor_client_id"] = None
    if result["actor_persona"] is not None:
        try:
            result["actor_client_id"] = _uuid(event.get("actor_client_id"))
        except ValueError:
            pass
    for name in ("succeeded_keys", "not_attempted"):
        if name in event:
            result[name] = _key_list(event[name])
    if "failed_key" in event:
        result["failed_key"] = _key(event["failed_key"])
    return result


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("History dates must be timezone-aware datetimes.")
    try:
        return value.astimezone(timezone.utc)
    except OverflowError:
        raise ValueError("History dates must be representable in UTC.") from None


def _blob_name(timestamp: datetime, event_id: str) -> str:
    return f"{timestamp:%Y-%m-%d}/{event_id}.json"


def _container(settings, credential) -> ContainerClient:
    return ContainerClient(
        account_url=settings[0], container_name=settings[1], credential=credential,
        connection_timeout=3, read_timeout=REQUEST_TIMEOUT,
        retry_policy=ExponentialRetry(
            initial_backoff=1, increment_base=1, retry_total=1, random_jitter_range=0,
        ),
        max_single_put_size=MAX_BLOB_BYTES,
        max_single_get_size=MAX_BLOB_BYTES + 1,
        max_chunk_get_size=MAX_BLOB_BYTES + 1,
    )


def _close(*resources):
    for resource in resources:
        if resource is not None:
            try:
                resource.close()
            except Exception:
                # Cleanup cannot change a confirmed upload/download result.
                pass


def record_event(event: dict) -> list[str]:
    """Synchronously record one event; fixed warnings never replace a write result.

    Caller IDs must be UUID strings. Operation/outcome choices are public above;
    key=None is for summaries/read probes, with no old/new values. A known absent
    setting is old_value=None, old_value_known=True, distinct from empty string.
    Extra keys are ignored. Invalid/oversized data is rejected, not silently cut.
    Explicit Log Analytics mode is a no-op (resource logs provide legacy history).
    """
    client = credential = None
    phase = "configuration"
    try:
        if rbac.comparison_mode() and not rbac.config_history_enabled():
            return []
        if backend() == "loganalytics":
            return []
        settings = _settings()
        phase = "event validation"
        document = _base_event(event)
        now = datetime.now(timezone.utc)
        event_id = str(uuid4())
        document.update(schema_version=1, event_id=event_id, timestamp=_timestamp(now), source="application")
        payload = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_BLOB_BYTES:
            raise ValueError("Event is too large.")
        phase = "writer identity"
        credential = rbac.audit_writer_credential()
        phase = "storage"
        client = _container(settings, credential)
        # Generate/serialize once. SDK retries reuse the same name and bytes;
        # never retry the App Configuration mutation or overwrite an event.
        client.upload_blob(
            name=_blob_name(now, event_id), data=payload, blob_type="BlockBlob",
            overwrite=False, content_settings=ContentSettings(content_type="application/json; charset=utf-8"),
            timeout=REQUEST_TIMEOUT,
        )
        return []
    except ResourceExistsError:
        return ["Change history persistence is unconfirmed after a create-only conflict; the configuration outcome is unchanged."]
    except ClientAuthenticationError:
        return ["Change history could not authenticate; the configuration outcome is unchanged."]
    except (ServiceRequestError, ServiceResponseError, TimeoutError):
        return ["Change history persistence is unconfirmed after a connection or timeout failure; the configuration outcome is unchanged."]
    except HttpResponseError:
        return ["Change history persistence is unconfirmed after a storage failure; the configuration outcome is unchanged."]
    except Exception:
        if phase == "storage":
            return ["Change history persistence is unconfirmed after a storage failure; the configuration outcome is unchanged."]
        return [f"Change history was not recorded ({phase}); the configuration outcome is unchanged."]
    finally:
        _close(client, credential)


def _decode_event(data: bytes, name: str) -> tuple[dict, datetime]:
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BLOB_BYTES:
        raise ValueError("Invalid event size.")
    event = json.loads(data.decode("utf-8"))
    if type(event) is not dict or type(event.get("schema_version")) is not int or event["schema_version"] != 1:
        raise ValueError("Unsupported event schema.")
    if event.get("source") != "application":
        raise ValueError("Unsupported event source.")
    timestamp = _text(event.get("timestamp"), 40)
    if timestamp is None:
        raise ValueError("Missing event timestamp.")
    instant = _utc(datetime.fromisoformat(timestamp.replace("Z", "+00:00")))
    event_id = _uuid(event.get("event_id"))
    if _blob_name(instant, event_id) != name:
        raise ValueError("Event name does not match its UTC date and ID.")
    result = _base_event(event)
    result.update(schema_version=1, event_id=event_id, timestamp=_timestamp(instant), source="application")
    return result, instant


def _partial(page: HistoryPage, warning: str):
    page.truncated = True
    if warning not in page.warnings:
        page.warnings.append(warning)


def _read(client: ContainerClient, start: datetime, end: datetime) -> HistoryPage:
    page = HistoryPage()
    deadline = monotonic() + MAX_READ_SECONDS
    listed = pages_read = downloads = bytes_read = 0
    day = (end - timedelta(microseconds=1)).date()
    stop = False

    def exhausted():
        return (monotonic() >= deadline or listed >= MAX_LISTED_BLOBS
                or downloads >= MAX_DOWNLOADS
                or bytes_read + MAX_BLOB_BYTES + 1 > MAX_DOWNLOAD_BYTES)

    while day >= start.date() and not stop:
        prefix = f"{day.isoformat()}/"
        pages = client.list_blobs(
            name_starts_with=prefix, results_per_page=LIST_PAGE_SIZE, timeout=REQUEST_TIMEOUT,
        ).by_page()
        while True:
            if exhausted() or pages_read >= MAX_LIST_PAGES:
                _partial(page, _LIMIT_WARNING)
                stop = True
                break
            try:
                items = next(pages)
            except StopIteration:
                break
            pages_read += 1
            for item in items:
                if exhausted():
                    _partial(page, _LIMIT_WARNING)
                    stop = True
                    break
                listed += 1
                name, size = getattr(item, "name", None), getattr(item, "size", None)
                if (type(name) is not str or not _BLOB_NAME.fullmatch(name) or not name.startswith(prefix)
                        or type(size) is not int or not 0 < size <= MAX_BLOB_BYTES):
                    _partial(page, _SKIP_WARNING)
                    continue
                downloads += 1
                try:
                    # Bound the actual response too, even if listing size is stale.
                    data = client.download_blob(
                        name, offset=0, length=MAX_BLOB_BYTES + 1,
                        max_concurrency=1, timeout=REQUEST_TIMEOUT,
                    ).readall()
                except ResourceNotFoundError:
                    _partial(page, _SKIP_WARNING)
                    continue
                bytes_read += len(data)
                try:
                    event, instant = _decode_event(data, name)
                except (ValueError, TypeError, RecursionError):
                    _partial(page, _SKIP_WARNING)
                    continue
                if start <= instant < end:
                    page.events.append(event)
            if stop:
                break
        if day == start.date():
            break
        day -= timedelta(days=1)
    page.events.sort(key=lambda event: (event["timestamp"], event["event_id"]), reverse=True)
    if len(page.events) > MAX_EVENTS:
        _partial(page, _LIMIT_WARNING)
        page.events = page.events[:MAX_EVENTS]
    return page


def load_events(start: datetime, end: datetime) -> HistoryPage:
    """Read bounded [start, end) history, never substituting an empty page on outage.

    Invalid time windows raise ValueError. Bad configuration, authorization,
    connection and other reader failures raise sanitized HistoryUnavailable.
    Malformed/missing individual blobs produce an explicitly partial page.
    """
    start, end = _utc(start), _utc(end)
    if end <= start or end - start > timedelta(days=MAX_HISTORY_DAYS):
        raise ValueError("History requires a positive interval of at most 30 days.")
    client = credential = None
    try:
        if rbac.comparison_mode() and not rbac.config_history_enabled():
            raise ValueError("Comparison history is disabled.")
        if backend() != "blob":
            raise ValueError("Blob history is not the selected backend.")
        settings = _settings()
        credential = rbac.service_credential("audit")
        client = _container(settings, credential)
        return _read(client, start, end)
    except Exception:
        raise HistoryUnavailable(
            "Application change history is unavailable; check the selected backend, Blob settings and audit reader access."
        ) from None
    finally:
        _close(client, credential)


def _csv_cell(value) -> str:
    if value is None:
        return ""
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        text = str(value) if abs(value) < 10**20 else ""
    elif type(value) is str:
        text = value[:MAX_VALUE_CHARS]
    elif isinstance(value, (list, tuple)):
        # Only known configuration keys are meaningful in publication summaries.
        text = "; ".join(key for key in value[:len(CONFIG_KEYS)] if type(key) is str and key in CONFIG_KEYS)
    else:
        return ""  # Never stringify arbitrary objects, dictionaries or exceptions.
    leading = 0
    while leading < len(text) and (text[leading].isspace() or unicodedata.category(text[leading]).startswith("C")):
        leading += 1
    if text[leading:leading + 1] in {"=", "+", "-", "@"}:
        return "'" + text
    return text


def export_csv(events) -> bytes:
    """Export only the supplied visible rows, in their order; never fetch history.

    Stable columns, BOM for Excel, RFC CSV quoting and formula neutralization.
    Lists are flattened only as approved-key summaries; nested metadata is not
    exported. This function deliberately applies no hidden filtering or limit.
    """
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for event in events:
        writer.writerow([_csv_cell(event.get(column)) for column in CSV_COLUMNS])
    return output.getvalue().encode("utf-8-sig")