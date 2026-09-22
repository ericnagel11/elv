"""Offline contract tests using real Azure SDK imports and mocked I/O.

No substitute azure modules, environment/credential files, or network requests.
The final transport test exercises actual SDK create-only upload and retry
behavior using an in-memory transport and a synthetic TokenCredential.
"""

import csv
from datetime import datetime, timedelta, timezone
import io
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from azure.core.credentials import AccessToken
from azure.core.exceptions import (
    ClientAuthenticationError, HttpResponseError, ResourceExistsError,
    ResourceNotFoundError, ServiceRequestError, ServiceResponseError,
)
from azure.core.pipeline.transport import HttpResponse, HttpTransport
from azure.storage.blob import ContainerClient

import change_history as history
import rbac

UTC = timezone.utc
START = datetime(2026, 9, 20, tzinfo=UTC)
END = START + timedelta(days=1)
OPERATION_ID = "10000000-0000-4000-8000-000000000001"
ACTOR_ID = "20000000-0000-4000-8000-000000000001"
WRITER_ID = "30000000-0000-4000-8000-000000000001"
BLOB_ENV = {
    "ELV_AUDIT_BLOB_ACCOUNT_URL": "https://testaccount.blob.core.windows.net",
    "ELV_AUDIT_BLOB_CONTAINER": "poc001-config-history",
}
RAW_ERROR = "private provider details sig=DO-NOT-EXPOSE bearer SECRET"


def input_event(**changes):
    event = {
        "operation_id": OPERATION_ID,
        "operation": "save", "store": "draft", "label": "candidate",
        "key": "knowledge:top_k", "old_value": "3", "new_value": "5",
        "old_value_known": True, "old_etag": "before", "new_etag": "after",
        "outcome": "success", "error_category": None,
        "actor_persona": "designer", "actor_client_id": ACTOR_ID,
    }
    event.update(changes)
    return event


def stored_event(number=1, instant=START, **changes):
    event = input_event()
    event.update(
        schema_version=1, event_id=str(UUID(int=number)),
        timestamp=instant.isoformat().replace("+00:00", "Z"), source="application",
    )
    event.update(changes)
    return event


def encoded(event):
    return json.dumps(event, ensure_ascii=False).encode("utf-8")


def blob_item(event, size=None):
    instant = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")).astimezone(UTC)
    return SimpleNamespace(
        name=f"{instant:%Y-%m-%d}/{event['event_id']}.json",
        size=len(encoded(event)) if size is None else size,
    )


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, BLOB_ENV, clear=True).start()
        # Catch accidental default RequestsTransport use as well as socket I/O.
        patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")).start()
        patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")).start()
        self.roles = patch.object(rbac, "_roles_file", side_effect=AssertionError("Credential file forbidden")).start()


class StorageTests(OfflineTests):
    def setUp(self):
        super().setUp()
        self.factory = patch.object(history, "ContainerClient", autospec=True).start()
        self.client = self.factory.return_value
        self.writer = patch.object(rbac, "audit_writer_credential").start()
        self.reader = patch.object(rbac, "service_credential").start()
        self.client.list_blobs.side_effect = lambda **kwargs: SimpleNamespace(by_page=lambda: iter([]))

    def fixtures(self, events):
        documents = {blob_item(event).name: encoded(event) for event in events}
        items = [blob_item(event) for event in events]

        def listing(**kwargs):
            matching = [item for item in items if item.name.startswith(kwargs["name_starts_with"])]
            return SimpleNamespace(by_page=lambda: iter([iter(matching)]))

        def download(name, **kwargs):
            return SimpleNamespace(readall=lambda: documents[name])

        self.client.list_blobs.side_effect = listing
        self.client.download_blob.side_effect = download

    def payload(self):
        return json.loads(self.client.upload_blob.call_args.kwargs["data"].decode("utf-8"))

    def assert_sanitized(self, values):
        self.assertTrue(values)
        self.assertNotIn(RAW_ERROR, str(values))
        self.assertNotIn("SECRET", str(values))

    def test_backend_defaults_to_blob_and_requires_explicit_legacy_mode(self):
        self.assertEqual(history.backend(), "blob")
        with patch.dict(os.environ, {"ELV_AUDIT_BACKEND": "loganalytics"}):
            self.assertEqual(history.backend(), "loganalytics")
            self.assertEqual(history.record_event({}), [])
        self.factory.assert_not_called()
        self.writer.assert_not_called()

    def test_invalid_backend_warns_on_write_and_raises_for_display_or_read(self):
        with patch.dict(os.environ, {"ELV_AUDIT_BACKEND": RAW_ERROR}):
            with self.assertRaises(ValueError) as caught:
                history.backend()
            self.assertNotIn(RAW_ERROR, str(caught.exception))
            self.assert_sanitized(history.record_event(input_event()))
            with self.assertRaises(history.HistoryUnavailable):
                history.load_events(START, END)
        self.factory.assert_not_called()

    def test_legacy_read_never_calls_blob_or_log_analytics(self):
        with patch.dict(os.environ, {"ELV_AUDIT_BACKEND": "loganalytics"}), \
                patch("azure.monitor.query.LogsQueryClient") as logs:
            with self.assertRaises(history.HistoryUnavailable):
                history.load_events(START, END)
        self.factory.assert_not_called()
        self.reader.assert_not_called()
        logs.assert_not_called()

    def test_account_url_validation_precedes_any_credential_or_storage_use(self):
        invalid = (
            "", "http://testaccount.blob.core.windows.net",
            "https://testaccount.blob.core.windows.net/path",
            "https://testaccount.blob.core.windows.net?sig=SECRET",
            "https://testaccount.blob.core.windows.net?",
            "https://testaccount.blob.core.windows.net/#fragment",
            "https://user:SECRET@testaccount.blob.core.windows.net",
            "https://testaccount.blob.core.windows.net:443",
            "https://testaccount.blob.core.windows.net.evil.example",
            "https://testaccount.blob.core.usgovcloudapi.net",
            "https://testaccount.dfs.core.windows.net",
            "https://localhost", "https://ab.blob.core.windows.net",
            "https://test-account.blob.core.windows.net",
        )
        for value in invalid:
            with self.subTest(value=value), patch.dict(os.environ, {"ELV_AUDIT_BLOB_ACCOUNT_URL": value}):
                self.assert_sanitized(history.record_event(input_event()))
                with self.assertRaises(history.HistoryUnavailable):
                    history.load_events(START, END)
        self.factory.assert_not_called()
        self.writer.assert_not_called()
        self.reader.assert_not_called()

    def test_invalid_container_names_are_rejected_without_creation(self):
        for value in ("", "ab", "A-container", "-abc", "abc-", "a--b", "a_b", "$root", "a/b", "a" * 64):
            with self.subTest(value=value), patch.dict(os.environ, {"ELV_AUDIT_BLOB_CONTAINER": value}):
                self.assertTrue(history.record_event(input_event()))
        self.factory.assert_not_called()

    def test_write_fills_reserved_fields_and_is_one_create_only_block_blob(self):
        event = input_event(
            event_id="spoofed", schema_version=99, source="portal", timestamp="spoofed",
            credentials={"secret": RAW_ERROR}, token=RAW_ERROR, metadata={"secret": RAW_ERROR},
            claims={"name": "not a human identity"}, error=RAW_ERROR,
        )
        original = dict(event)
        with patch.dict(os.environ, {"ELV_AUDIT_BLOB_ACCOUNT_URL": BLOB_ENV["ELV_AUDIT_BLOB_ACCOUNT_URL"] + "/"}):
            self.assertEqual(history.record_event(event), [])
        self.assertEqual(event, original)
        self.writer.assert_called_once_with()
        self.reader.assert_not_called()
        self.client.upload_blob.assert_called_once()
        args = self.client.upload_blob.call_args.kwargs
        result = self.payload()
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["source"], "application")
        self.assertEqual(UUID(result["event_id"]).version, 4)
        self.assertTrue(result["timestamp"].endswith("Z"))
        self.assertEqual(args["name"], result["timestamp"][:10] + "/" + result["event_id"] + ".json")
        self.assertEqual(args["blob_type"], "BlockBlob")
        self.assertIs(args["overwrite"], False)
        self.assertLessEqual(len(args["data"]), history.MAX_BLOB_BYTES)
        self.assertEqual(args["timeout"], history.REQUEST_TIMEOUT)
        self.assertNotIn(b"SECRET", args["data"])
        self.assertNotIn("metadata", args)
        self.assertEqual(result["old_value"], "3")
        self.assertEqual(result["new_value"], "5")
        self.assertEqual(result["actor_client_id"], ACTOR_ID)
        self.assertLessEqual(set(result), set(history.CSV_COLUMNS))
        self.client.create_container.assert_not_called()
        self.client.close.assert_called_once()
        self.writer.return_value.close.assert_called_once()
        options = self.factory.call_args.kwargs
        self.assertEqual(options["account_url"], BLOB_ENV["ELV_AUDIT_BLOB_ACCOUNT_URL"])
        self.assertEqual(options["credential"], self.writer.return_value)
        self.assertEqual(options["read_timeout"], history.REQUEST_TIMEOUT)
        self.assertGreater(options["connection_timeout"], 0)

    def test_absent_empty_and_unknown_before_values_remain_distinct(self):
        for value, known in ((None, True), ("", True), (None, False)):
            with self.subTest(value=value, known=known):
                self.assertEqual(history.record_event(input_event(old_value=value, old_value_known=known)), [])
                self.assertIs(self.payload()["old_value_known"], known)
                self.assertEqual(self.payload()["old_value"], value)

    def test_field_mapping_changes_are_allowlisted_history_not_full_demo_edit_permission(self):
        import config

        event = input_event(key="knowledge:content_field", old_value="content", new_value="Content")
        self.assertEqual(history.record_event(event), [])
        self.assertEqual(self.payload()["key"], "knowledge:content_field")
        self.assertNotIn("knowledge:content_field", config.FULL_DEMO_KEYS)
        with patch.object(config, "_client") as client:
            with self.assertRaises(ValueError):
                config.set_value("content_field", "Content", persona="designer", prefix="knowledge:")
            client.assert_not_called()

    def test_only_approved_keys_and_bounded_typed_fields_are_recorded(self):
        cases = (
            {"key": "application:secret"}, {"key": "knowledge:unsupported"},
            {"new_value": {"client_secret": RAW_ERROR}},
            {"old_value": "a" * (history.MAX_VALUE_CHARS + 1)},
            {"old_value_known": "true"}, {"old_value_known": False},
            {"key": None}, {"operation_id": "not-a-uuid"},
            {"operation": RAW_ERROR}, {"outcome": RAW_ERROR},
            {"store": "https://arbitrary"}, {"old_etag": "a" * 257},
            {"label": "a" * 129}, {"succeeded_keys": ["client_secret"]},
            {"not_attempted": ["knowledge:top_k"] * (len(history.CONFIG_KEYS) + 1)}, {"failed_key": "secret"},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                self.assert_sanitized(history.record_event(input_event(**changes)))
        self.factory.assert_not_called()
        self.writer.assert_not_called()

    def test_raw_error_categories_and_invalid_actor_metadata_cannot_leak(self):
        for category in (RAW_ERROR, RuntimeError(RAW_ERROR), {"secret": RAW_ERROR}):
            self.assertEqual(history.record_event(input_event(
                error_category=category, actor_persona=RAW_ERROR, actor_client_id=RAW_ERROR,
            )), [])
            result = self.payload()
            self.assertEqual(result["error_category"], "unknown")
            self.assertIsNone(result["actor_persona"])
            self.assertIsNone(result["actor_client_id"])
            self.assertNotIn("SECRET", str(result))
        self.assertEqual(history.record_event(input_event(actor_client_id=RAW_ERROR)), [])
        self.assertIsNone(self.payload()["actor_client_id"])

    def test_publication_summary_retains_group_and_key_lists(self):
        event = input_event(
            operation="publish_summary", store="production", key=None,
            old_value=None, new_value=None, old_value_known=False, outcome="partial",
            succeeded_keys=["experience:tone", "knowledge:enabled"],
            failed_key="knowledge:filter", not_attempted=["knowledge:top_k"],
        )
        self.assertEqual(history.record_event(event), [])
        result = self.payload()
        for name in ("operation_id", "succeeded_keys", "failed_key", "not_attempted", "outcome"):
            self.assertEqual(result[name], event[name])

    def test_probe_can_have_no_key_or_values(self):
        event = input_event(operation="permission_probe", key=None, old_value=None, new_value=None, old_value_known=False)
        self.assertEqual(history.record_event(event), [])
        self.assertEqual(self.payload()["operation"], "permission_probe")

    def test_serialized_byte_budget_is_checked_before_identity(self):
        with patch.object(history, "MAX_BLOB_BYTES", 100):
            self.assert_sanitized(history.record_event(input_event()))
        self.writer.assert_not_called()

    def test_invalid_unicode_becomes_a_warning_not_a_mutation_exception(self):
        self.assert_sanitized(history.record_event(input_event(new_value="\ud800")))
        self.writer.assert_not_called()

    def test_all_upload_failures_are_sanitized_without_application_retry(self):
        failures = (
            ClientAuthenticationError(RAW_ERROR), HttpResponseError(RAW_ERROR),
            ServiceRequestError(RAW_ERROR), ServiceResponseError(RAW_ERROR),
            TimeoutError(RAW_ERROR), ResourceExistsError(RAW_ERROR),
            ResourceNotFoundError(RAW_ERROR), RuntimeError(RAW_ERROR),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.client.upload_blob.reset_mock()
                self.client.upload_blob.side_effect = failure
                self.assert_sanitized(history.record_event(input_event()))
                self.client.upload_blob.assert_called_once()

    def test_writer_validation_and_cleanup_failures_do_not_escape(self):
        self.writer.side_effect = ValueError(RAW_ERROR)
        self.assert_sanitized(history.record_event(input_event()))
        self.factory.assert_not_called()
        self.writer.side_effect = None
        self.client.close.side_effect = RuntimeError(RAW_ERROR)
        self.writer.return_value.close.side_effect = RuntimeError(RAW_ERROR)
        self.assertEqual(history.record_event(input_event()), [])

    def test_empty_history_is_a_complete_page_only_after_successful_listing(self):
        self.assertEqual(history.load_events(START, END), history.HistoryPage())
        self.reader.assert_called_once_with("audit")
        self.writer.assert_not_called()
        self.assertEqual(self.factory.call_args.kwargs["credential"], self.reader.return_value)
        self.client.list_blobs.assert_called_once_with(
            name_starts_with="2026-09-20/", results_per_page=history.LIST_PAGE_SIZE, timeout=history.REQUEST_TIMEOUT,
        )
        self.client.download_blob.assert_not_called()
        self.client.close.assert_called_once()
        self.reader.return_value.close.assert_called_once()

    def test_read_sorts_utc_descending_and_respects_half_open_range(self):
        events = [
            stored_event(1, START), stored_event(2, START + timedelta(hours=12)),
            stored_event(3, START + timedelta(hours=23)), stored_event(4, END),
            stored_event(5, START - timedelta(microseconds=1)),
        ]
        self.fixtures(events)
        page = history.load_events(START, END)
        self.assertFalse(page.truncated)
        self.assertEqual([e["event_id"] for e in page.events], [events[i]["event_id"] for i in (2, 1, 0)])
        self.assertEqual(len(self.client.list_blobs.call_args_list), 1)
        for request in self.client.download_blob.call_args_list:
            self.assertEqual(request.kwargs["length"], history.MAX_BLOB_BYTES + 1)
            self.assertEqual(request.kwargs["offset"], 0)
            self.assertEqual(request.kwargs["max_concurrency"], 1)

    def test_timezone_conversion_and_only_utc_day_prefixes(self):
        local = timezone(timedelta(hours=-7))
        start = datetime(2026, 9, 19, 17, tzinfo=local)
        history.load_events(start, start + timedelta(hours=24))
        self.assertEqual(self.client.list_blobs.call_args.kwargs["name_starts_with"], "2026-09-20/")
        self.client.list_blobs.reset_mock()
        history.load_events(START - timedelta(days=1, hours=1), END - timedelta(hours=1))
        self.assertEqual(
            [call.kwargs["name_starts_with"] for call in self.client.list_blobs.call_args_list],
            ["2026-09-20/", "2026-09-19/", "2026-09-18/"],
        )

    def test_invalid_windows_fail_before_credentials_or_storage(self):
        windows = (
            (START, START), (END, START), (START, START + timedelta(days=30, microseconds=1)),
            (START.replace(tzinfo=None), END), (START, "not a date"),
        )
        for start, end in windows:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                history.load_events(start, end)
        self.reader.assert_not_called()
        self.factory.assert_not_called()

    def test_exactly_thirty_days_is_valid_and_listings_are_bounded_by_dates(self):
        page = history.load_events(START, START + timedelta(days=30))
        self.assertFalse(page.truncated)
        self.assertEqual(self.client.list_blobs.call_count, 30)

    def test_reader_failures_are_sanitized_unavailable_not_empty_results(self):
        failures = (
            ClientAuthenticationError(RAW_ERROR), HttpResponseError(RAW_ERROR),
            ServiceRequestError(RAW_ERROR), ServiceResponseError(RAW_ERROR),
            TimeoutError(RAW_ERROR), ResourceNotFoundError(RAW_ERROR), RuntimeError(RAW_ERROR),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.client.list_blobs.side_effect = failure
                with self.assertRaises(history.HistoryUnavailable) as caught:
                    history.load_events(START, END)
                self.assertNotIn(RAW_ERROR, str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
                self.assertTrue(caught.exception.__suppress_context__)

    def test_download_auth_or_connection_failure_discards_partial_results(self):
        events = [stored_event(1), stored_event(2)]
        for failure in (ClientAuthenticationError(RAW_ERROR), ServiceRequestError(RAW_ERROR)):
            with self.subTest(failure=type(failure).__name__):
                self.fixtures(events)
                self.client.download_blob.side_effect = [
                    SimpleNamespace(readall=lambda: encoded(events[0])), failure,
                ]
                with self.assertRaises(history.HistoryUnavailable):
                    history.load_events(START, END)

    def test_missing_blob_is_partial_but_preserves_other_events(self):
        events = [stored_event(1), stored_event(2)]
        self.fixtures(events)
        self.client.download_blob.side_effect = [
            ResourceNotFoundError(RAW_ERROR), SimpleNamespace(readall=lambda: encoded(events[1])),
        ]
        page = history.load_events(START, END)
        self.assertTrue(page.truncated)
        self.assertEqual(len(page.events), 1)
        self.assert_sanitized(page.warnings)

    def test_malformed_oversized_and_wrong_name_events_are_skipped_honestly(self):
        valid = stored_event()
        wrong_schema = stored_event(schema_version=2)
        wrong_id = stored_event(event_id=str(UUID(int=99)))
        cases = (
            b"not json", b"\xff", b"[]", encoded(wrong_schema), encoded(wrong_id),
            encoded(stored_event(source="portal")), encoded(stored_event(timestamp="bad")),
            encoded(stored_event(timestamp="2026-09-20T00:00:00")),
            encoded(stored_event(key="secret")), b"x" * (history.MAX_BLOB_BYTES + 1),
            json.dumps(stored_event(new_value="\ud800")).encode("utf-8"),
            encoded(stored_event(timestamp="0001-01-01T00:00:00+01:00")),
            b"[" * 2000 + b"]" * 2000,
        )
        for data in cases:
            with self.subTest(length=len(data)):
                self.fixtures([valid])
                self.client.download_blob.side_effect = None
                self.client.download_blob.return_value.readall.return_value = data
                page = history.load_events(START, END)
                self.assertEqual(page.events, [])
                self.assertTrue(page.truncated)
                self.assertTrue(page.warnings)

    def test_bad_listed_names_and_sizes_are_not_downloaded(self):
        items = [
            SimpleNamespace(name="2026-09-20/../secret.json", size=10),
            SimpleNamespace(name="2026-09-19/" + str(UUID(int=1)) + ".json", size=10),
            blob_item(stored_event(), size=history.MAX_BLOB_BYTES + 1),
            blob_item(stored_event(), size=0), blob_item(stored_event(), size="100"),
        ]
        self.client.list_blobs.side_effect = lambda **kwargs: SimpleNamespace(by_page=lambda: iter([iter(items)]))
        page = history.load_events(START, END)
        self.assertTrue(page.truncated)
        self.assertEqual(len(page.warnings), 1)
        self.client.download_blob.assert_not_called()

    def test_unknown_stored_metadata_is_removed_from_visible_rows(self):
        self.fixtures([stored_event(token=RAW_ERROR, claims={"human": RAW_ERROR}, metadata={"secret": RAW_ERROR})])
        page = history.load_events(START, END)
        self.assertFalse(page.truncated)
        self.assertNotIn("SECRET", str(page.events))
        self.assertNotIn("claims", page.events[0])

    def test_row_limit_uses_sorted_rows_and_reports_partial(self):
        events = [stored_event(i + 1, START + timedelta(seconds=i)) for i in range(history.MAX_EVENTS + 1)]
        self.fixtures(events)
        page = history.load_events(START, END)
        self.assertEqual(len(page.events), 500)
        self.assertEqual(page.events[0]["event_id"], events[-1]["event_id"])
        self.assertTrue(page.truncated)
        self.assertIn("not guaranteed", " ".join(page.warnings))

    def test_listing_and_download_budgets_stop_before_an_unbounded_scan(self):
        events = [stored_event(i + 1) for i in range(5)]
        for limit in ("MAX_LISTED_BLOBS", "MAX_DOWNLOADS"):
            with self.subTest(limit=limit), patch.object(history, limit, 2):
                self.fixtures(events)
                self.client.download_blob.reset_mock()
                page = history.load_events(START, END)
                self.assertTrue(page.truncated)
                self.assertEqual(len(page.events), 2)
                self.assertEqual(self.client.download_blob.call_count, 2)

    def test_listing_page_budget_includes_empty_pages(self):
        self.client.list_blobs.side_effect = lambda **kwargs: SimpleNamespace(by_page=lambda: iter([[], [], [], []]))
        with patch.object(history, "MAX_LIST_PAGES", 2):
            page = history.load_events(START, END)
        self.assertTrue(page.truncated)
        self.client.download_blob.assert_not_called()

    def test_byte_and_time_budgets_stop_before_another_download(self):
        self.fixtures([stored_event(1), stored_event(2)])
        with patch.object(history, "MAX_DOWNLOAD_BYTES", history.MAX_BLOB_BYTES + 1):
            page = history.load_events(START, END)
        self.assertTrue(page.truncated)
        self.assertEqual(self.client.download_blob.call_count, 1)
        self.client.download_blob.reset_mock()
        with patch.object(history, "monotonic", side_effect=[0, history.MAX_READ_SECONDS + 1]):
            page = history.load_events(START, END)
        self.assertTrue(page.truncated)
        self.client.download_blob.assert_not_called()


class IdentityTests(OfflineTests):
    def identity_env(self):
        return {
            **BLOB_ENV, "ELV_HOSTING_MODE": "azure-vm", "ELV_AUDIT_BLOB_WRITER_CLIENT_ID": WRITER_ID,
            **{f"ELV_MI_{name.upper()}_CLIENT_ID": str(UUID(int=i))
               for i, name in enumerate([*rbac.PERSONAS, "audit"], start=1)},
        }

    def test_vm_writer_is_explicit_and_does_not_touch_existing_persona_selector(self):
        with patch.dict(os.environ, self.identity_env(), clear=True), \
                patch("azure.identity.ManagedIdentityCredential") as managed, \
                patch.object(rbac, "DefaultAzureCredential") as developer, \
                patch.object(rbac.hosting, "identity_ids") as identities:
            self.assertIs(rbac.audit_writer_credential(), managed.return_value)
        managed.assert_called_once_with(client_id=WRITER_ID)
        identities.assert_not_called()
        developer.assert_not_called()
        self.roles.assert_not_called()

    def test_vm_writer_rejects_missing_zero_invalid_reader_or_shared_id_without_fallback(self):
        env = self.identity_env()
        bad_writers = ["", "not-a-uuid", str(UUID(int=0))]
        bad_writers.extend(env[f"ELV_MI_{name.upper()}_CLIENT_ID"].upper() for name in [*rbac.PERSONAS, "audit"])
        with patch("azure.identity.ManagedIdentityCredential") as managed, \
                patch.object(rbac, "DefaultAzureCredential") as developer:
            for writer in bad_writers:
                with self.subTest(writer=writer), patch.dict(os.environ, {**env, "ELV_AUDIT_BLOB_WRITER_CLIENT_ID": writer}, clear=True):
                    with self.assertRaises(ValueError):
                        rbac.audit_writer_credential()
            for reader in ("", "not-a-uuid", str(UUID(int=0))):
                with patch.dict(os.environ, {**env, "ELV_MI_AUDIT_CLIENT_ID": reader}, clear=True):
                    with self.assertRaises(ValueError):
                        rbac.audit_writer_credential()
        managed.assert_not_called()
        developer.assert_not_called()

    def test_invalid_writer_does_not_participate_in_existing_persona_validation(self):
        env = {**self.identity_env(), "ELV_AUDIT_BLOB_WRITER_CLIENT_ID": "bad"}
        with patch.dict(os.environ, env, clear=True), patch.object(rbac.hosting, "ManagedIdentityCredential") as managed:
            self.assertTrue(rbac.personas_configured())
            self.assertEqual(rbac.credential_warnings(), [])
            rbac.credential_for("designer")
            managed.assert_called_with(client_id=env["ELV_MI_DESIGNER_CLIENT_ID"])
            rbac.service_credential("audit")
            managed.assert_called_with(client_id=env["ELV_MI_AUDIT_CLIENT_ID"])

    def test_writer_failure_is_lazy_and_best_effort_inside_recorder(self):
        env = {**self.identity_env(), "ELV_AUDIT_BLOB_WRITER_CLIENT_ID": "bad"}
        with patch.dict(os.environ, env, clear=True), patch.object(history, "ContainerClient") as factory:
            self.assertTrue(history.record_event(input_event()))
        factory.assert_not_called()

    def test_development_writer_uses_default_credential_without_roles_file(self):
        with patch.object(rbac, "DefaultAzureCredential") as developer, \
                patch("azure.identity.ManagedIdentityCredential") as managed:
            self.assertIs(rbac.audit_writer_credential(), developer.return_value)
        developer.assert_called_once_with()
        managed.assert_not_called()
        self.roles.assert_not_called()

    def test_vm_actor_only_uses_nonsecret_configured_uuid(self):
        env = self.identity_env()
        with patch.dict(os.environ, env, clear=True), \
                patch.object(rbac.hosting, "identity_ids", side_effect=AssertionError("Global validation forbidden")), \
                patch("azure.identity.ManagedIdentityCredential") as managed:
            self.assertEqual(rbac.actor_metadata("designer"), {
                "actor_persona": "designer", "actor_client_id": env["ELV_MI_DESIGNER_CLIENT_ID"],
            })
        managed.assert_not_called()
        self.roles.assert_not_called()

    def test_development_actor_returns_only_allowlisted_metadata_not_credentials(self):
        self.roles.side_effect = None
        self.roles.return_value = {"tenantId": RAW_ERROR, "personas": {"designer": {
            "clientId": ACTOR_ID.upper(), "clientSecret": RAW_ERROR, "displayName": RAW_ERROR,
        }}}
        with patch.object(rbac, "credential_for") as credential:
            self.assertEqual(rbac.actor_metadata("designer"), {
                "actor_persona": "designer", "actor_client_id": ACTOR_ID,
            })
        credential.assert_not_called()

    def test_actor_mapping_errors_missing_and_invalid_ids_never_block(self):
        self.roles.side_effect = None
        for data in ({}, None, [], {"personas": []}, {"personas": {"designer": []}},
                     {"personas": {"designer": {"clientId": RAW_ERROR}}}):
            self.roles.return_value = data
            self.assertEqual(rbac.actor_metadata("designer"), {"actor_persona": "designer", "actor_client_id": None})
        self.roles.side_effect = RuntimeError(RAW_ERROR)
        self.assertIsNone(rbac.actor_metadata("designer")["actor_client_id"])
        for persona in (None, [], RAW_ERROR):
            self.assertEqual(rbac.actor_metadata(persona), {"actor_persona": None, "actor_client_id": None})
        with patch.dict(os.environ, {"ELV_HOSTING_MODE": "bad"}):
            self.assertIsNone(rbac.actor_metadata("designer")["actor_client_id"])


class CsvTests(OfflineTests):
    def rows(self, events):
        data = history.export_csv(events)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline="")))

    def test_stable_columns_and_only_passed_rows_in_their_order(self):
        selected = [stored_event(3), stored_event(1)]
        with patch.object(history, "load_events", side_effect=AssertionError("No fetch during export")):
            rows = self.rows(selected)
        self.assertEqual(tuple(rows[0]), history.CSV_COLUMNS)
        self.assertEqual([row["event_id"] for row in rows], [event["event_id"] for event in selected])
        empty = history.export_csv([]).decode("utf-8-sig")
        self.assertEqual(empty, ",".join(history.CSV_COLUMNS) + "\r\n")

    def test_quotes_newlines_unicode_and_summary_keys_round_trip(self):
        text = 'Member said "hello",\nnext line\r\nEspañol 日本語'
        event = stored_event(
            old_value=text, new_value="", old_value_known=True,
            succeeded_keys=["experience:tone", "knowledge:enabled"],
            failed_key="knowledge:filter", not_attempted=["knowledge:top_k"],
        )
        row = self.rows([event])[0]
        self.assertEqual(row["old_value"], text)
        self.assertEqual(row["new_value"], "")
        self.assertEqual(row["old_value_known"], "true")
        self.assertEqual(row["succeeded_keys"], "experience:tone; knowledge:enabled")
        self.assertEqual(row["not_attempted"], "knowledge:top_k")

    def test_formula_prefixes_after_whitespace_and_controls_are_neutralized(self):
        for prefix in ("", " ", "\t", "\r\n", "\x00", "\x01 ", "\u200b", "\ufeff", "\u00a0"):
            for operator in "=+-@":
                with self.subTest(prefix=repr(prefix), operator=operator):
                    text = prefix + operator + "HYPERLINK(\"https://example.invalid\")"
                    row = self.rows([stored_event(old_value=text, new_value=text, label=text)])[0]
                    for column in ("old_value", "new_value", "label"):
                        self.assertEqual(row[column], "'" + text)

    def test_nested_arbitrary_metadata_and_exceptions_are_not_stringified(self):
        row = self.rows([stored_event(
            metadata={"secret": RAW_ERROR}, token=RAW_ERROR,
            old_value={"secret": RAW_ERROR}, new_value=RuntimeError(RAW_ERROR),
            succeeded_keys=[{"secret": RAW_ERROR}, "knowledge:enabled", RAW_ERROR],
        )])[0]
        self.assertNotIn("SECRET", str(row))
        self.assertEqual(row["old_value"], "")
        self.assertEqual(row["new_value"], "")
        self.assertEqual(row["succeeded_keys"], "knowledge:enabled")


class MemoryResponse(HttpResponse):
    def __init__(self, request):
        super().__init__(request, None)
        self.status_code = 201
        self.reason = "Created"
        self.headers = {"etag": '"offline-etag"', "x-ms-request-id": "offline"}
        self.content_type = "application/xml"

    def body(self):
        return b""


class RetryTransport(HttpTransport):
    """Fail the first send, then succeed, without ever touching a real socket."""

    def __init__(self):
        self.calls = []
        self.sleeps = []

    def open(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def sleep(self, duration):
        self.sleeps.append(duration)

    def send(self, request, **kwargs):
        body = request.body
        if hasattr(body, "getvalue"):
            body = body.getvalue()
        self.calls.append((request.url, body, dict(request.headers)))
        if len(self.calls) == 1:
            raise ServiceRequestError(RAW_ERROR)
        return MemoryResponse(request)


class RealSdkTests(OfflineTests):
    def test_retry_reuses_exact_payload_and_blob_id_with_conditional_create(self):
        transport = RetryTransport()
        # A bare Mock invents get_token_info, causing newer azure-core to use
        # that instead of get_token. Model only the actual TokenCredential API.
        credential = Mock(spec=["get_token", "close"])
        credential.get_token.return_value = AccessToken("offline-test-token", 4102444800)

        def client_factory(**kwargs):
            return ContainerClient(**kwargs, transport=transport)

        with patch.object(history, "ContainerClient", side_effect=client_factory), \
                patch.object(rbac, "audit_writer_credential", return_value=credential):
            self.assertEqual(history.record_event(input_event()), [])
        self.assertEqual(len(transport.calls), 2)
        first, second = transport.calls
        self.assertEqual(first[:2], second[:2])
        payload = json.loads(first[1])
        self.assertIn(payload["event_id"] + ".json", first[0])
        for _, _, headers in transport.calls:
            normalized = {key.lower(): value for key, value in headers.items()}
            self.assertEqual(normalized["if-none-match"], "*")
            self.assertEqual(normalized["x-ms-blob-type"], "BlockBlob")


class ComparisonHistoryIdentityTests(OfflineTests):
    def setUp(self):
        super().setUp()
        os.environ.update({
            "ELV_HOSTING_MODE": "azure-vm", "ELV_DEMO_MODE": "comparison",
            "ELV_MI_APP_CLIENT_ID": ACTOR_ID,
        })

    def test_history_is_off_by_default_without_credential_or_storage_calls(self):
        with patch.object(history, "ContainerClient") as container, \
                patch.object(rbac, "ManagedIdentityCredential") as credential:
            self.assertFalse(rbac.config_history_enabled())
            self.assertEqual(history.record_event(input_event()), [])
            with self.assertRaises(history.HistoryUnavailable):
                history.load_events(START, END)
            with self.assertRaises(rbac.OperationDisabled):
                rbac.audit_writer_credential()
            with self.assertRaises(rbac.OperationDisabled):
                rbac.service_credential("audit")
            credential.assert_not_called()
            container.assert_not_called()

    def test_explicit_opt_in_uses_only_runtime_identity_for_writer_and_reader(self):
        os.environ["ELV_ENABLE_CONFIG_HISTORY"] = "true"
        with patch.object(rbac, "ManagedIdentityCredential") as credential, \
                patch.object(rbac, "DefaultAzureCredential", side_effect=AssertionError("fallback")), \
                patch.object(rbac, "ClientSecretCredential", side_effect=AssertionError("secret")):
            self.assertTrue(rbac.config_history_enabled())
            self.assertIs(rbac.audit_writer_credential(), credential.return_value)
            self.assertIs(rbac.service_credential("audit"), credential.return_value)
            self.assertEqual(credential.call_count, 2)
            credential.assert_called_with(client_id=ACTOR_ID)
            self.roles.assert_not_called()

    def test_invalid_flag_or_runtime_id_fails_before_credentials(self):
        with patch.object(rbac, "ManagedIdentityCredential") as credential:
            os.environ["ELV_ENABLE_CONFIG_HISTORY"] = "yes"
            with self.assertRaisesRegex(ValueError, "ELV_ENABLE_CONFIG_HISTORY"):
                rbac.audit_writer_credential()
            os.environ["ELV_ENABLE_CONFIG_HISTORY"] = "true"
            os.environ["ELV_MI_APP_CLIENT_ID"] = ""
            with self.assertRaisesRegex(ValueError, "ELV_MI_APP_CLIENT_ID"):
                rbac.service_credential("audit")
            credential.assert_not_called()

    def test_history_opt_in_does_not_enable_other_personas_or_full_governance(self):
        os.environ["ELV_ENABLE_CONFIG_HISTORY"] = "true"
        with self.assertRaises(rbac.OperationDisabled):
            rbac.credential_for("approver")
        with self.assertRaises(rbac.OperationDisabled):
            rbac.require_full_demo("Publishing")


if __name__ == "__main__":
    unittest.main()