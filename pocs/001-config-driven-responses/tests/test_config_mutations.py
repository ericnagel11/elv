"""Offline mutation contracts using real SDK models and mocked service boundaries.

App Configuration, event persistence, and actor metadata are always mocked.
Credential/file/network guards also fail the test if an unintended path is used.
No environment setup, substitute Azure modules, or real credentials are needed.
"""

from copy import deepcopy
import unittest
from unittest.mock import Mock, call, patch
from uuid import UUID

from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting
from azure.core import MatchConditions
from azure.core.exceptions import (
    HttpResponseError, ResourceNotFoundError, ServiceRequestError, ServiceResponseError,
)

import change_history
import config
import rbac
from search_settings import DEFAULTS


ACTOR_ID = "20000000-0000-4000-8000-000000000001"
OPERATION_ID = "10000000-0000-4000-8000-000000000001"
HISTORY_WARNING = "History unavailable in the offline fixture."
RAW_ERROR = "Synthetic private provider details DO-NOT-EXPOSE"


def setting(key="experience:tone", value="before", *, etag="etag-before",
            label="candidate", content_type="text/plain", tags=None):
    return ConfigurationSetting(
        key=key, label=label, value=value, etag=etag, content_type=content_type,
        tags={"owner": "governance", "keep": "yes"} if tags is None else tags,
    )


def http_error(status):
    error = HttpResponseError(message=RAW_ERROR)
    error.status_code = status
    return error


class MutationResultTests(unittest.TestCase):
    def test_defaults_have_unique_ids_and_independent_lists(self):
        first, second = config.MutationResult(), config.MutationResult()
        self.assertEqual(UUID(first.operation_id).version, 4)
        self.assertNotEqual(first.operation_id, second.operation_id)
        self.assertEqual(second.outcome, "success")
        self.assertIsNone(second.failed_key)
        for name in ("changed_keys", "unchanged_keys", "audit_warnings", "not_attempted"):
            self.assertEqual(getattr(first, name), [])
            self.assertIsNot(getattr(first, name), getattr(second, name))
            getattr(first, name).append("fixture")
            self.assertEqual(getattr(second, name), [])


class OfflineMutationTests(unittest.TestCase):
    def start_patch(self, patcher):
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def setUp(self):
        self.persona = "designer"
        self.guards = []
        for name in ("credential_for", "service_credential", "audit_writer_credential", "_roles_file"):
            self.guards.append(self.start_patch(patch.object(
                rbac, name, side_effect=AssertionError("Credentials and credential files forbidden"),
            )))
        self.guards.append(self.start_patch(patch.object(
            config, "AzureAppConfigurationClient",
            side_effect=AssertionError("Real App Configuration client forbidden"),
        )))
        for target in ("requests.sessions.Session.request", "socket.socket.connect"):
            self.guards.append(self.start_patch(patch(
                target, side_effect=AssertionError("Network forbidden"),
            )))
        self.clients = {
            store: Mock(spec_set=AzureAppConfigurationClient)
            for store in ("draft", "production")
        }
        self.draft = self.clients["draft"]
        self.production = self.clients["production"]
        for client in self.clients.values():
            client.list_configuration_settings.return_value = []
            client.get_configuration_setting.side_effect = (
                lambda *, key, label: setting(key, label=label)
            )
            client.set_configuration_setting.side_effect = (
                lambda value, **kwargs: setting(value.key, value.value, etag="etag-after", label=value.label)
            )
            client.add_configuration_setting.side_effect = (
                lambda value: setting(value.key, value.value, etag="etag-created", label=value.label)
            )
        self.client_factory = self.start_patch(patch.object(
            config, "_client", side_effect=lambda store, persona: self.clients[store],
        ))
        self.history = self.start_patch(patch.object(change_history, "record_event", return_value=[]))
        self.actor = self.start_patch(patch.object(
            rbac, "actor_metadata",
            side_effect=lambda persona: {"actor_persona": persona, "actor_client_id": ACTOR_ID},
        ))

    def tearDown(self):
        # A forbidden call must fail even if production's best-effort boundary
        # catches the guard's AssertionError and returns a warning instead.
        for guard in self.guards:
            guard.assert_not_called()

    def events(self):
        return [entry.args[0] for entry in self.history.call_args_list]

    def assert_no_writes(self):
        for client in self.clients.values():
            client.set_configuration_setting.assert_not_called()
            client.add_configuration_setting.assert_not_called()

    def assert_result(self, result, *, changed=(), unchanged=(), warnings=(),
                      outcome="success", failed=None, not_attempted=()):
        self.assertIsInstance(result, config.MutationResult)
        self.assertEqual(UUID(result.operation_id).version, 4)
        self.assertEqual(result.changed_keys, list(changed))
        self.assertEqual(result.unchanged_keys, list(unchanged))
        self.assertEqual(result.audit_warnings, list(warnings))
        self.assertEqual(result.outcome, outcome)
        self.assertEqual(result.failed_key, failed)
        self.assertEqual(result.not_attempted, list(not_attempted))

    def assert_summary(self, result):
        events = self.events()
        summaries = [event for event in events if event["operation"] == "publish_summary"]
        self.assertEqual(len(summaries), 1)
        self.assertIs(events[-1], summaries[0])
        self.assertEqual({event["operation_id"] for event in events}, {result.operation_id})
        self.assertEqual(summaries[0], {
            "operation_id": result.operation_id, "operation": "publish_summary",
            "store": "production", "label": "candidate", "key": None,
            "old_value": None, "new_value": None, "old_value_known": False,
            "old_etag": None, "new_etag": None, "outcome": result.outcome,
            "error_category": None, "succeeded_keys": result.changed_keys,
            "failed_key": result.failed_key, "not_attempted": result.not_attempted,
            "actor_persona": self.persona, "actor_client_id": ACTOR_ID,
        })

    def seed_draft(self, experience, knowledge, timeline=None):
        profiles = {config.EXPERIENCE_PREFIX: experience, config.KNOWLEDGE_PREFIX: knowledge}

        def listing(*, key_filter, label_filter):
            prefix = key_filter[:-1]
            self.assertEqual(key_filter, prefix + "*")
            self.assertEqual(label_filter, config.DRAFT_LABEL)
            if timeline is not None:
                timeline.append(("draft", prefix))
            return iter(setting(prefix + key, value) for key, value in profiles[prefix].items())

        self.draft.list_configuration_settings.side_effect = listing


class SetValueTests(OfflineMutationTests):
    def test_permission_probe_rewrites_fresh_value_not_stale_profile_value(self):
        self.draft.get_configuration_setting.side_effect = None
        self.draft.get_configuration_setting.return_value = setting(value="newer-value")
        config.set_value("tone", "stale-profile-value", persona=self.persona,
                         operation="permission_probe", force=True)
        self.assertEqual(self.draft.set_configuration_setting.call_args.args[0].value, "newer-value")
        self.assertEqual(self.events()[0]["old_value"], "newer-value")
        self.assertEqual(self.events()[0]["new_value"], "newer-value")

    def test_permission_probe_does_not_recreate_a_deleted_key(self):
        self.draft.get_configuration_setting.side_effect = ResourceNotFoundError()
        with self.assertRaises(ValueError):
            config.set_value("tone", "stale-profile-value", persona=self.persona,
                             operation="permission_probe", force=True)
        self.assert_no_writes()
        self.assertEqual(self.events()[0]["outcome"], "failed")

    def test_changed_existing_value_preserves_metadata_and_records_both_etags(self):
        before = setting(value="formal", tags={"owner": "member-support", "keep": "yes"})
        self.draft.get_configuration_setting.side_effect = None
        self.draft.get_configuration_setting.return_value = before
        order = Mock()
        order.attach_mock(self.draft.get_configuration_setting, "read")
        order.attach_mock(self.draft.set_configuration_setting, "write")
        order.attach_mock(self.history, "record")

        result = config.set_value("tone", "warm", persona=self.persona, operation_id=OPERATION_ID)

        self.assert_result(result, changed=["experience:tone"])
        self.assertEqual(result.operation_id, OPERATION_ID)
        self.client_factory.assert_called_once_with("draft", self.persona)
        self.draft.get_configuration_setting.assert_called_once_with(key="experience:tone", label="candidate")
        self.draft.set_configuration_setting.assert_called_once()
        written = self.draft.set_configuration_setting.call_args.args[0]
        self.assertIsInstance(written, ConfigurationSetting)
        self.assertEqual((written.key, written.label, written.value), ("experience:tone", "candidate", "warm"))
        self.assertEqual(written.content_type, before.content_type)
        self.assertEqual(written.tags, before.tags)
        self.assertIsNot(written.tags, before.tags)
        self.assertEqual(before.value, "formal")
        self.assertEqual(before.etag, "etag-before")
        self.assertEqual(self.draft.set_configuration_setting.call_args.kwargs, {
            "etag": "etag-before", "match_condition": MatchConditions.IfNotModified,
        })
        self.draft.add_configuration_setting.assert_not_called()
        self.actor.assert_called_once_with(self.persona)
        self.history.assert_called_once_with({
            "operation_id": OPERATION_ID, "operation": "save", "store": "draft",
            "label": "candidate", "key": "experience:tone", "old_value": "formal",
            "new_value": "warm", "old_value_known": True,
            "old_etag": "etag-before", "new_etag": "etag-after", "outcome": "success",
            "error_category": None, "actor_persona": self.persona, "actor_client_id": ACTOR_ID,
        })
        self.assertEqual([entry[0] for entry in order.mock_calls], ["read", "write", "record"])
        self.assertEqual(self.production.mock_calls, [])

    def test_absent_key_uses_create_only_add_and_distinguishes_missing_from_empty(self):
        self.draft.get_configuration_setting.side_effect = ResourceNotFoundError("Absent fixture")

        result = config.set_value("tone", "", persona=self.persona)

        self.assert_result(result, changed=["experience:tone"])
        self.draft.add_configuration_setting.assert_called_once()
        written = self.draft.add_configuration_setting.call_args.args[0]
        self.assertEqual((written.key, written.label, written.value), ("experience:tone", "candidate", ""))
        self.assertEqual(written.tags, {})
        self.assertIsNone(written.content_type)
        self.assertEqual(self.draft.add_configuration_setting.call_args.kwargs, {})
        self.draft.set_configuration_setting.assert_not_called()
        self.history.assert_called_once()
        event = self.events()[0]
        self.assertIsNone(event["old_value"])
        self.assertIs(event["old_value_known"], True)
        self.assertEqual(event["new_value"], "")
        self.assertIsNone(event["old_etag"])
        self.assertEqual(event["new_etag"], "etag-created")
        self.assertEqual(event["operation_id"], result.operation_id)

    def test_equal_values_including_empty_are_noops_without_history_or_actor_lookup(self):
        self.draft.get_configuration_setting.side_effect = None
        for value in ("warm", ""):
            with self.subTest(value=value):
                self.draft.get_configuration_setting.reset_mock()
                self.draft.get_configuration_setting.return_value = setting(value=value)
                result = config.set_value("tone", value, persona=self.persona)
                self.assert_result(result, unchanged=["experience:tone"], outcome="unchanged")
                self.draft.get_configuration_setting.assert_called_once()
                self.assert_no_writes()
                self.history.assert_not_called()
                self.actor.assert_not_called()

    def test_forced_same_value_probe_writes_conditionally_and_records_exactly_once(self):
        result = config.set_value(
            "tone", "before", persona=self.persona, force=True, operation="permission_probe",
        )
        self.assert_result(result, changed=["experience:tone"])
        self.draft.set_configuration_setting.assert_called_once()
        self.assertEqual(self.draft.set_configuration_setting.call_args.kwargs, {
            "etag": "etag-before", "match_condition": MatchConditions.IfNotModified,
        })
        self.history.assert_called_once()
        event = self.events()[0]
        self.assertEqual(event["operation"], "permission_probe")
        self.assertEqual(event["outcome"], "allowed")
        self.assertEqual(event["old_value"], event["new_value"])
        self.assertEqual((event["old_etag"], event["new_etag"]), ("etag-before", "etag-after"))

    def test_missing_existing_etag_fails_before_a_write(self):
        self.draft.get_configuration_setting.side_effect = None
        self.draft.get_configuration_setting.return_value = setting(etag=None)
        with self.assertRaises(ValueError) as caught:
            config.set_value("tone", "warm", persona=self.persona)
        self.assert_result(caught.exception.mutation_result, outcome="failed", failed="experience:tone")
        self.assert_no_writes()
        self.history.assert_called_once()
        self.assertEqual(self.events()[0]["error_category"], "validation")

    def test_history_warning_does_not_retry_or_reverse_a_successful_write(self):
        self.history.return_value = [HISTORY_WARNING]
        result = config.set_value("tone", "warm", persona=self.persona)
        self.assert_result(result, changed=["experience:tone"], warnings=[HISTORY_WARNING])
        self.draft.get_configuration_setting.assert_called_once()
        self.draft.set_configuration_setting.assert_called_once()
        self.draft.add_configuration_setting.assert_not_called()
        self.history.assert_called_once()
        self.assertEqual(self.events()[0]["outcome"], "success")

    def test_accidental_record_event_exception_is_a_sanitized_warning_not_a_retry(self):
        self.history.side_effect = RuntimeError(RAW_ERROR)
        result = config.set_value("tone", "warm", persona=self.persona)
        self.assertEqual(len(result.audit_warnings), 1)
        self.assertNotIn(RAW_ERROR, result.audit_warnings[0])
        self.assert_result(result, changed=["experience:tone"], warnings=result.audit_warnings)
        self.draft.get_configuration_setting.assert_called_once()
        self.draft.set_configuration_setting.assert_called_once()
        self.draft.add_configuration_setting.assert_not_called()
        self.history.assert_called_once()

    def test_actor_metadata_exception_cannot_undo_a_successful_write(self):
        self.actor.side_effect = RuntimeError(RAW_ERROR)
        result = config.set_value("tone", "warm", persona=self.persona)
        self.assertEqual(len(result.audit_warnings), 1)
        self.assertNotIn(RAW_ERROR, result.audit_warnings[0])
        self.assert_result(result, changed=["experience:tone"], warnings=result.audit_warnings)
        self.draft.set_configuration_setting.assert_called_once()
        self.actor.assert_called_once_with(self.persona)
        self.history.assert_not_called()

    def test_config_denial_stays_access_denied_with_result_despite_history_failure(self):
        for phase in ("read", "write"):
            for throws in (False, True):
                with self.subTest(phase=phase, history_throws=throws):
                    self.draft.reset_mock()
                    self.history.reset_mock()
                    denied = http_error(403)
                    self.draft.get_configuration_setting.side_effect = denied if phase == "read" else None
                    self.draft.get_configuration_setting.return_value = setting()
                    self.draft.set_configuration_setting.side_effect = denied if phase == "write" else None
                    self.history.return_value = [HISTORY_WARNING]
                    self.history.side_effect = RuntimeError(RAW_ERROR) if throws else None

                    with self.assertRaises(config.AccessDenied) as caught:
                        config.set_value("tone", "warm", persona=self.persona)

                    error = caught.exception
                    result = error.mutation_result
                    self.assertIs(error.__cause__, denied)
                    self.assertEqual(error.store, "draft")
                    self.assertEqual(error.operation, "update tone" if phase == "write" else "read tone before update")
                    self.assertEqual(len(result.audit_warnings), 1)
                    self.assertNotIn(RAW_ERROR, result.audit_warnings[0])
                    if not throws:
                        self.assertEqual(result.audit_warnings, [HISTORY_WARNING])
                    self.assert_result(result, outcome="denied", failed="experience:tone", warnings=result.audit_warnings)
                    self.draft.get_configuration_setting.assert_called_once()
                    self.assertEqual(self.draft.set_configuration_setting.call_count, int(phase == "write"))
                    self.draft.add_configuration_setting.assert_not_called()
                    self.history.assert_called_once()
                    event = self.events()[0]
                    self.assertEqual((event["outcome"], event["error_category"]), ("denied", "authorization"))
                    self.assertEqual(event["old_value_known"], phase == "write")
                    self.assertEqual(event["old_value"], "before" if phase == "write" else None)
                    self.assertEqual(event["operation_id"], result.operation_id)
                    self.assertIsNone(event["new_etag"])

    def test_existing_412_conflict_preserves_exception_and_never_retries(self):
        conflict = http_error(412)
        self.draft.set_configuration_setting.side_effect = conflict
        with self.assertRaises(HttpResponseError) as caught:
            config.set_value("tone", "warm", persona=self.persona)
        self.assertIs(caught.exception, conflict)
        self.assertEqual(caught.exception.status_code, 412)
        self.assert_result(conflict.mutation_result, outcome="conflict", failed="experience:tone")
        self.draft.get_configuration_setting.assert_called_once()
        self.draft.set_configuration_setting.assert_called_once()
        self.draft.add_configuration_setting.assert_not_called()
        self.history.assert_called_once()
        event = self.events()[0]
        self.assertEqual((event["outcome"], event["error_category"]), ("conflict", "conflict"))
        self.assertEqual(event["old_etag"], "etag-before")
        self.assertIsNone(event["new_etag"])

    def test_absent_key_create_conflict_does_not_fall_back_to_overwrite(self):
        conflict = http_error(409)
        self.draft.get_configuration_setting.side_effect = ResourceNotFoundError("Absent fixture")
        self.draft.add_configuration_setting.side_effect = conflict
        with self.assertRaises(HttpResponseError) as caught:
            config.set_value("tone", "warm", persona=self.persona)
        self.assertIs(caught.exception, conflict)
        self.assert_result(conflict.mutation_result, outcome="conflict", failed="experience:tone")
        self.draft.add_configuration_setting.assert_called_once()
        self.draft.set_configuration_setting.assert_not_called()
        self.history.assert_called_once()
        self.assertIs(self.events()[0]["old_value_known"], True)
        self.assertIsNone(self.events()[0]["old_value"])

    def test_write_timeouts_have_unknown_outcome_without_a_retry(self):
        for error_type in (TimeoutError, ServiceRequestError, ServiceResponseError):
            with self.subTest(error_type=error_type.__name__):
                self.draft.reset_mock()
                self.history.reset_mock()
                failure = error_type(RAW_ERROR)
                self.draft.set_configuration_setting.side_effect = failure
                with self.assertRaises(error_type) as caught:
                    config.set_value("tone", "warm", persona=self.persona)
                self.assertIs(caught.exception, failure)
                self.assert_result(failure.mutation_result, outcome="unknown", failed="experience:tone")
                self.draft.get_configuration_setting.assert_called_once()
                self.draft.set_configuration_setting.assert_called_once()
                self.draft.add_configuration_setting.assert_not_called()
                self.history.assert_called_once()
                event = self.events()[0]
                self.assertEqual((event["outcome"], event["error_category"]), ("unknown", "connection"))
                self.assertIs(event["old_value_known"], True)
                self.assertIsNone(event["new_etag"])

    def test_read_timeout_is_failed_not_an_unknown_write(self):
        failure = TimeoutError(RAW_ERROR)
        self.draft.get_configuration_setting.side_effect = failure
        with self.assertRaises(TimeoutError) as caught:
            config.set_value("tone", "warm", persona=self.persona)
        self.assertIs(caught.exception, failure)
        self.assert_result(failure.mutation_result, outcome="failed", failed="experience:tone")
        self.assert_no_writes()
        self.history.assert_called_once()
        event = self.events()[0]
        self.assertEqual((event["outcome"], event["error_category"]), ("failed", "connection"))
        self.assertIs(event["old_value_known"], False)
        self.assertIsNone(event["old_value"])

    def test_invalid_single_mutations_do_not_obtain_a_client(self):
        cases = (
            {"short_key": "unsupported"}, {"store": "other"}, {"label": "other"},
            {"value": None}, {"value": "x" * (change_history.MAX_VALUE_CHARS + 1)},
            {"short_key": "top_k", "value": "21", "prefix": config.KNOWLEDGE_PREFIX},
        )
        for changes in cases:
            with self.subTest(fields=list(changes)):
                arguments = {"short_key": "tone", "value": "warm", "persona": self.persona, **changes}
                with self.assertRaises(ValueError):
                    config.set_value(**arguments)
        self.client_factory.assert_not_called()
        self.assert_no_writes()
        self.history.assert_not_called()


class SaveKnowledgeTests(OfflineMutationTests):
    def test_all_range_enum_and_index_validation_precedes_any_write(self):
        invalid = (
            ("top_k", "0"), ("top_k", 21), ("top_k", True),
            ("query_mode", "vector"), ("citation_style", "link"),
            ("index", "Bad Index"), ("index", "a/b"), ("enabled", "maybe"),
        )
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                # An earlier valid change exposes validation deferred until
                # each individual write, especially for index/query_mode/top_k.
                submitted = {**DEFAULTS, "citation_style": "footnote", key: value}
                original = deepcopy(submitted)
                with self.assertRaises(ValueError):
                    config.save_knowledge(submitted, persona=self.persona)
                self.assertEqual(submitted, original)
                self.client_factory.assert_not_called()
                self.assert_no_writes()
                self.history.assert_not_called()

    def test_oversized_filter_is_validated_before_any_batch_write(self):
        # Regression contract: the per-setting size limit must be validated for
        # the whole form, not discovered after earlier keys were committed.
        submitted = {**DEFAULTS, "filter": "x" * (change_history.MAX_VALUE_CHARS + 1)}
        with self.assertRaises(ValueError):
            config.save_knowledge(submitted, persona=self.persona)
        self.assert_no_writes()
        self.client_factory.assert_not_called()
        self.history.assert_not_called()

    def test_normalized_save_writes_only_changed_draft_keys_with_one_operation_id(self):
        self.draft.get_configuration_setting.side_effect = (
            lambda *, key, label: setting(key, DEFAULTS[key.split(":", 1)[1]], label=label)
        )
        submitted = {
            "enabled": True, "index": " kb-current ", "filter": " \n ",
            "top_k": " 05 ", "query_mode": " SEMANTIC ", "citation_style": " FOOTNOTE ",
        }
        original = deepcopy(submitted)
        expected = {
            "knowledge:citation_style": "footnote", "knowledge:enabled": "true",
            "knowledge:filter": "", "knowledge:query_mode": "semantic", "knowledge:top_k": "5",
        }

        result = config.save_knowledge(submitted, persona=self.persona)

        self.assert_result(result, changed=sorted(expected), unchanged=["knowledge:index"])
        self.assertEqual(submitted, original)
        writes = self.draft.set_configuration_setting.call_args_list
        self.assertEqual({entry.args[0].key: entry.args[0].value for entry in writes}, expected)
        self.assertEqual(len(writes), len(expected))
        self.assertTrue(all(entry.args[0].label == "candidate" for entry in writes))
        self.assertTrue(all(entry.kwargs == {
            "etag": "etag-before", "match_condition": MatchConditions.IfNotModified,
        } for entry in writes))
        self.assertEqual(self.draft.get_configuration_setting.call_count, 6)
        self.draft.add_configuration_setting.assert_not_called()
        self.assertEqual(self.client_factory.call_args_list, [call("draft", self.persona)] * 6)
        self.assertEqual(self.production.mock_calls, [])
        events = self.events()
        self.assertEqual([event["key"] for event in events], sorted(expected))
        self.assertEqual({event["operation_id"] for event in events}, {result.operation_id})
        self.assertEqual({event["operation"] for event in events}, {"save"})
        self.assertEqual({event["store"] for event in events}, {"draft"})

    def test_noop_search_save_reports_all_unchanged_without_events(self):
        self.draft.get_configuration_setting.side_effect = (
            lambda *, key, label: setting(key, DEFAULTS[key.split(":", 1)[1]], label=label)
        )
        result = config.save_knowledge(dict(DEFAULTS), persona=self.persona)
        self.assert_result(result, unchanged=sorted("knowledge:" + key for key in DEFAULTS), outcome="unchanged")
        self.assert_no_writes()
        self.history.assert_not_called()
        self.actor.assert_not_called()

    def test_partial_search_save_stops_and_attaches_completed_failed_and_unattempted_keys(self):
        self.draft.set_configuration_setting.side_effect = [
            setting("knowledge:citation_style", "inline", etag="etag-after"), http_error(403),
        ]
        self.history.side_effect = [["Completed-key history warning"], ["Failed-key history warning"]]
        with self.assertRaises(config.AccessDenied) as caught:
            config.save_knowledge(dict(DEFAULTS), persona=self.persona)
        result = caught.exception.mutation_result
        self.assert_result(
            result, changed=["knowledge:citation_style"], failed="knowledge:enabled", outcome="partial",
            not_attempted=["knowledge:filter", "knowledge:index", "knowledge:query_mode", "knowledge:top_k"],
            warnings=["Completed-key history warning", "Failed-key history warning"],
        )
        self.assertEqual(self.draft.get_configuration_setting.call_args_list, [
            call(key="knowledge:citation_style", label="candidate"),
            call(key="knowledge:enabled", label="candidate"),
        ])
        self.assertEqual(self.draft.set_configuration_setting.call_count, 2)
        self.draft.add_configuration_setting.assert_not_called()
        self.assertEqual(self.production.mock_calls, [])
        events = self.events()
        self.assertEqual([event["outcome"] for event in events], ["success", "denied"])
        self.assertEqual({event["operation_id"] for event in events}, {result.operation_id})
        self.assertEqual({event["operation"] for event in events}, {"save"})


class PublishDraftTests(OfflineMutationTests):
    def setUp(self):
        super().setUp()
        self.persona = "approver"

    def test_both_prefixes_are_captured_before_writing_and_snapshot_is_used(self):
        experience = {"tone": "warm", "persona": "member support"}
        knowledge = {"top_k": " 05 ", "enabled": "TRUE", "filter": ""}
        timeline = []
        self.seed_draft(experience, knowledge, timeline)
        expected = {
            "experience:persona": "member support", "experience:tone": "warm",
            "knowledge:enabled": "true", "knowledge:filter": "", "knowledge:top_k": "5",
        }

        def read(*, key, label):
            timeline.append(("read", key))
            return setting(key, label=label)

        def write(value, **kwargs):
            timeline.append(("write", value.key))
            # A later draft edit must not change values already captured for
            # this publication, including keys not yet written to production.
            experience["tone"] = "later draft edit"
            knowledge["top_k"] = "19"
            return setting(value.key, value.value, etag="etag-after")

        self.production.get_configuration_setting.side_effect = read
        self.production.set_configuration_setting.side_effect = write
        result = config.publish_draft(persona=self.persona)

        self.assert_result(result, changed=sorted(expected))
        self.assertEqual(timeline, [("draft", "experience:"), ("draft", "knowledge:")] + [
            entry for key in sorted(expected) for entry in (("read", key), ("write", key))
        ])
        self.assertEqual(self.draft.list_configuration_settings.call_args_list, [
            call(key_filter="experience:*", label_filter="candidate"),
            call(key_filter="knowledge:*", label_filter="candidate"),
        ])
        writes = self.production.set_configuration_setting.call_args_list
        self.assertEqual({entry.args[0].key: entry.args[0].value for entry in writes}, expected)
        self.assertEqual(len(writes), len(expected))
        for entry in writes:
            self.assertEqual(entry.args[0].label, "candidate")
            self.assertEqual(entry.kwargs, {"etag": "etag-before", "match_condition": MatchConditions.IfNotModified})
        self.assertEqual(self.client_factory.call_args_list,
                         [call("draft", self.persona)] * 2 + [call("production", self.persona)] * len(expected))
        self.draft.set_configuration_setting.assert_not_called()
        self.draft.add_configuration_setting.assert_not_called()
        self.production.add_configuration_setting.assert_not_called()
        self.assert_summary(result)
        self.assertEqual([event["key"] for event in self.events()[:-1]], sorted(expected))
        self.assertTrue(all(event["operation"] == "publish_key" for event in self.events()[:-1]))
        self.assertTrue(all(event["store"] == "production" for event in self.events()))

    def test_entire_snapshot_is_validated_before_any_production_read_or_write(self):
        cases = (
            ({"tone": "warm"}, {"top_k": "21"}),
            ({"tone": "warm"}, {"query_mode": "vector"}),
            ({"tone": "warm"}, {"citation_style": "link"}),
            ({"tone": "warm"}, {"index": "Bad Index"}),
            ({"tone": "warm", "unsupported": "value"}, {}),
            ({"tone": "warm", "verbosity": None}, {}),
            ({"tone": "warm", "verbosity": "x" * (change_history.MAX_VALUE_CHARS + 1)}, {}),
            ({"tone": "warm"}, {"filter": "x" * (change_history.MAX_VALUE_CHARS + 1)}),
        )
        for number, (experience, knowledge) in enumerate(cases):
            with self.subTest(case=number):
                self.history.reset_mock()
                self.production.reset_mock()
                self.seed_draft(experience, knowledge)
                with self.assertRaises(ValueError) as caught:
                    config.publish_draft(persona=self.persona)
                self.assert_result(caught.exception.mutation_result, outcome="failed")
                self.assert_no_writes()
                self.assertEqual(self.production.mock_calls, [])
                self.history.assert_called_once()
                self.assert_summary(caught.exception.mutation_result)

    def test_unsupported_knowledge_key_rejects_snapshot_instead_of_silently_dropping_it(self):
        # Keep a valid key in each prefix: silently filtering the unknown key
        # otherwise looks like a successful, complete publication.
        self.seed_draft({"tone": "warm"}, {"top_k": "5", "unsupported": "value"})
        with self.assertRaises(ValueError) as caught:
            config.publish_draft(persona=self.persona)
        self.assert_result(caught.exception.mutation_result, outcome="failed")
        self.assert_no_writes()
        self.assertEqual(self.production.mock_calls, [])
        self.history.assert_called_once()
        self.assert_summary(caught.exception.mutation_result)

    def test_failure_loading_either_draft_prefix_still_records_one_publish_summary(self):
        self.history.return_value = [HISTORY_WARNING]
        for prefix in ("experience:", "knowledge:"):
            with self.subTest(prefix=prefix):
                self.history.reset_mock()
                self.draft.reset_mock()
                denied = http_error(403)
                self.draft.list_configuration_settings.side_effect = (
                    [denied] if prefix == "experience:" else [[setting(value="warm")], denied]
                )
                with self.assertRaises(config.AccessDenied) as caught:
                    config.publish_draft(persona=self.persona)
                result = caught.exception.mutation_result
                self.assertIs(caught.exception.__cause__, denied)
                self.assertEqual(caught.exception.store, "draft")
                self.assert_result(result, outcome="denied", warnings=[HISTORY_WARNING])
                self.assert_no_writes()
                self.assertEqual(self.production.mock_calls, [])
                self.history.assert_called_once()
                self.assert_summary(result)

    def test_empty_draft_is_a_failed_publication_not_a_successful_noop(self):
        self.seed_draft({}, {})
        with self.assertRaises(ValueError) as caught:
            config.publish_draft(persona=self.persona)
        self.assert_result(caught.exception.mutation_result, outcome="failed")
        self.assert_no_writes()
        self.history.assert_called_once()
        self.assert_summary(caught.exception.mutation_result)

    def test_partial_publish_reports_unchanged_completed_failed_and_unattempted_with_shared_id(self):
        self.seed_draft(
            {"persona": "before", "tone": "warm", "verbosity": "brief"},
            {"index": "kb-current", "top_k": "5"},
        )
        conflict = http_error(412)
        self.production.set_configuration_setting.side_effect = [
            setting("experience:tone", "warm", etag="etag-after"), conflict,
        ]
        self.history.side_effect = [["Completed warning"], ["Conflict warning"], ["Summary warning"]]
        with self.assertRaises(HttpResponseError) as caught:
            config.publish_draft(persona=self.persona)

        self.assertIs(caught.exception, conflict)
        result = conflict.mutation_result
        self.assert_result(
            result, changed=["experience:tone"], unchanged=["experience:persona"],
            failed="experience:verbosity", not_attempted=["knowledge:index", "knowledge:top_k"],
            outcome="partial", warnings=["Completed warning", "Conflict warning", "Summary warning"],
        )
        self.assertEqual(self.production.get_configuration_setting.call_args_list, [
            call(key="experience:persona", label="candidate"),
            call(key="experience:tone", label="candidate"),
            call(key="experience:verbosity", label="candidate"),
        ])
        self.assertEqual(self.production.set_configuration_setting.call_count, 2)
        self.production.add_configuration_setting.assert_not_called()
        self.draft.set_configuration_setting.assert_not_called()
        self.assert_summary(result)
        self.assertEqual([event["operation"] for event in self.events()], ["publish_key", "publish_key", "publish_summary"])
        self.assertEqual([event["outcome"] for event in self.events()], ["success", "conflict", "partial"])
        self.assertEqual([event["key"] for event in self.events()], ["experience:tone", "experience:verbosity", None])

    def test_failure_of_first_publish_write_is_conflict_not_partial_or_success(self):
        self.seed_draft({"tone": "warm"}, {"top_k": "5"})
        conflict = http_error(412)
        self.production.set_configuration_setting.side_effect = conflict
        with self.assertRaises(HttpResponseError) as caught:
            config.publish_draft(persona=self.persona)
        self.assertIs(caught.exception, conflict)
        result = conflict.mutation_result
        self.assert_result(result, outcome="conflict", failed="experience:tone", not_attempted=["knowledge:top_k"])
        self.production.get_configuration_setting.assert_called_once()
        self.production.set_configuration_setting.assert_called_once()
        self.assert_summary(result)
        self.assertEqual([event["outcome"] for event in self.events()], ["conflict", "conflict"])

    def test_noop_publish_has_only_one_unchanged_summary_and_no_key_events(self):
        values = {"experience:tone": "warm", "knowledge:index": "kb-current", "knowledge:top_k": "3"}
        self.seed_draft({"tone": "warm"}, {"index": "kb-current", "top_k": "3"})
        self.production.get_configuration_setting.side_effect = (
            lambda *, key, label: setting(key, values[key], label=label)
        )
        result = config.publish_draft(persona=self.persona)
        self.assert_result(result, unchanged=sorted(values), outcome="unchanged")
        self.assertEqual(self.production.get_configuration_setting.call_count, len(values))
        self.assert_no_writes()
        self.history.assert_called_once()
        self.assert_summary(result)

    def test_summary_history_exception_warns_without_retrying_any_publication_write(self):
        self.seed_draft({"tone": "warm"}, {"top_k": "5"})

        def record(event):
            if event["operation"] == "publish_summary":
                raise RuntimeError(RAW_ERROR)
            return []

        self.history.side_effect = record
        result = config.publish_draft(persona=self.persona)
        self.assertEqual(len(result.audit_warnings), 1)
        self.assertNotIn(RAW_ERROR, result.audit_warnings[0])
        self.assert_result(result, changed=["experience:tone", "knowledge:top_k"], warnings=result.audit_warnings)
        self.assertEqual(self.production.get_configuration_setting.call_count, 2)
        self.assertEqual(self.production.set_configuration_setting.call_count, 2)
        self.production.add_configuration_setting.assert_not_called()
        self.assertEqual(self.history.call_count, 3)
        self.assert_summary(result)


class PermissionProbeTests(OfflineMutationTests):
    def setUp(self):
        super().setUp()
        for client in self.clients.values():
            client.list_configuration_settings.return_value = [
                setting("experience:verbosity", "brief"), setting("experience:tone", "before"),
            ]
        self.history.return_value = [HISTORY_WARNING]

    def assert_four_probe_events(self, results):
        self.assertEqual([row["operation"] for row in results], [
            "Read live experience", "Read draft experience", "Edit draft experience", "Publish to production",
        ])
        events = self.events()
        self.assertEqual(len(events), 4)
        self.assertEqual({event["operation"] for event in events}, {"permission_probe"})
        self.assertEqual([event["store"] for event in events], ["production", "draft", "draft", "production"])
        self.assertEqual(len({event["operation_id"] for event in events}), 4)
        for event in events:
            self.assertEqual(UUID(event["operation_id"]).version, 4)
        self.assertTrue(all(row["audit_warnings"] == [HISTORY_WARNING] for row in results))

    def test_allowed_probes_force_same_value_writes_without_duplicate_records(self):
        results = config.probe(self.persona)
        self.assert_four_probe_events(results)
        self.assertTrue(all(row["allowed"] is True and row["outcome"] == "Allowed" for row in results))
        self.assertEqual([event["key"] for event in self.events()], [None, None, "experience:tone", "experience:tone"])
        self.assertTrue(all(event["outcome"] == "allowed" for event in self.events()))
        for event in self.events()[2:]:
            self.assertEqual(event["old_value"], "before")
            self.assertEqual(event["new_value"], "before")
            self.assertEqual(event["new_etag"], "etag-after")
        for client in self.clients.values():
            client.get_configuration_setting.assert_called_once_with(key="experience:tone", label="candidate")
            client.set_configuration_setting.assert_called_once()
            self.assertEqual(client.set_configuration_setting.call_args.kwargs, {
                "etag": "etag-before", "match_condition": MatchConditions.IfNotModified,
            })
            client.add_configuration_setting.assert_not_called()

    def test_denied_internal_probe_writes_are_not_recorded_twice(self):
        for client in self.clients.values():
            client.set_configuration_setting.side_effect = http_error(403)
        results = config.probe(self.persona)
        self.assert_four_probe_events(results)
        self.assertEqual([row["allowed"] for row in results], [True, True, False, False])
        self.assertEqual([row["outcome"] for row in results[2:]], ["Denied by Azure (403)"] * 2)
        self.assertEqual([event["key"] for event in self.events()], [None, None, "experience:tone", "experience:tone"])
        self.assertEqual([event["outcome"] for event in self.events()], ["allowed", "allowed", "denied", "denied"])
        for client in self.clients.values():
            client.set_configuration_setting.assert_called_once()
            client.add_configuration_setting.assert_not_called()

    def test_empty_profile_before_internal_write_gets_exactly_one_summary_per_probe(self):
        for client in self.clients.values():
            client.list_configuration_settings.side_effect = [[setting()], []]
        results = config.probe(self.persona)
        self.assert_four_probe_events(results)
        self.assertEqual([row["allowed"] for row in results], [True, True, None, None])
        self.assertTrue(all(row["outcome"].startswith("Inconclusive:") for row in results[2:]))
        self.assertTrue(all(event["key"] is None for event in self.events()))
        self.assertEqual([event["outcome"] for event in self.events()], ["allowed", "allowed", "failed", "failed"])
        self.assert_no_writes()
        for client in self.clients.values():
            client.get_configuration_setting.assert_not_called()

    def test_denied_reads_and_prewrite_loads_each_get_one_probe_summary(self):
        for client in self.clients.values():
            client.list_configuration_settings.side_effect = http_error(403)
        results = config.probe(self.persona)
        self.assert_four_probe_events(results)
        self.assertTrue(all(row["allowed"] is False for row in results))
        self.assertTrue(all(event["key"] is None and event["outcome"] == "denied" for event in self.events()))
        self.assert_no_writes()
        for client in self.clients.values():
            client.get_configuration_setting.assert_not_called()

    def test_timed_out_probe_writes_remain_unknown_and_are_not_double_logged(self):
        self.draft.set_configuration_setting.side_effect = TimeoutError(RAW_ERROR)
        self.production.set_configuration_setting.side_effect = ServiceResponseError(RAW_ERROR)
        results = config.probe(self.persona)
        self.assert_four_probe_events(results)
        self.assertEqual([row["allowed"] for row in results], [True, True, None, None])
        self.assertTrue(all(row["outcome"].startswith("Inconclusive:") for row in results[2:]))
        self.assertEqual([event["outcome"] for event in self.events()], ["allowed", "allowed", "unknown", "unknown"])
        for client in self.clients.values():
            client.set_configuration_setting.assert_called_once()
            client.add_configuration_setting.assert_not_called()


if __name__ == "__main__":
    unittest.main()