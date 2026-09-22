"""Offline integration tests of the actual PoC001 Streamlit entrypoint.

Run with the other PoC001 unittest tests and its installed requirements. The
app is never imported by this module: AppTest executes it only after patches
are active, including the providers of its directly imported aliases. Real
Streamlit caches, widgets, form validation and reruns remain under test.

No application data files, credentials, models, HTTP services or subprocesses
are used. AppTest reads the existing source (not a generated temporary script);
normal framework/package reads are allowed. CSV downloads stay in memory.
Global patches/cache clearing mean these tests must not run concurrently in
the same process as another Streamlit app.
"""

import builtins
import csv
import datetime as dt
import io
import os
from pathlib import Path
import socket
import sys
import threading
from contextlib import ExitStack
from copy import deepcopy
from types import ModuleType
import unittest
from unittest.mock import Mock, call, patch

import streamlit as st
from streamlit.testing.v1 import AppTest

import a2a_client
import audit
import change_history
import config as cfg
import experience_runtime
import hosting
import rbac
from search_settings import DEFAULT_QUESTION, DEFAULTS


APP_PATH = Path(__file__).absolute().parents[1] / "app.py"
REAL_RUN_GROUNDED = experience_runtime.run_grounded
REAL_LOAD_EVENTS = change_history.load_events
AUDIT_WARNING = "Change history was not recorded; the configuration outcome is unchanged."
SEARCH_CONTROLS = {
    "enabled": ("toggle", "Enable Search grounding", False),
    "index": ("text_input", "Search index or alias", DEFAULTS["index"]),
    "filter": ("text_area", "OData filter", DEFAULTS["filter"]),
    "top_k": ("number_input", "Top documents (top_k)", 3),
    "query_mode": ("selectbox", "Query mode", "simple"),
    "citation_style": ("selectbox", "Citation style", "inline"),
}


def model_result():
    return {
        "text": "Synthetic member-support response; review the denial notice.",
        "messages": [], "latency_s": 0.01, "finish_reason": "stop",
        "prompt_tokens": 10, "completion_tokens": 8, "reasoning_tokens": 0,
    }


def preview_bundle():
    return {
        "result": model_result(), "grounded": False,
        "found": {"documents": [], "notes": ["Offline preview."], "index": None},
    }


def history_event(number, **overrides):
    event = {
        "schema_version": 1, "event_id": f"00000000-0000-4000-8000-{number:012d}",
        "operation_id": "00000000-0000-4000-8000-000000000100",
        "timestamp": "2026-09-21T10:00:00Z", "source": "application",
        "operation": "save", "store": "production", "label": "candidate",
        "key": "experience:tone", "old_value": "formal", "new_value": "warm",
        "old_value_known": True, "old_etag": "old", "new_etag": "new",
        "outcome": "success", "error_category": None,
        "actor_persona": "approver", "actor_client_id": None,
    }
    event.update(overrides)
    return event


class AppIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            # Streamlit resolves a home directory even with all application
            # configuration mocked. Use a synthetic path, never the user's home.
            "USERPROFILE": str(APP_PATH.parent / "offline-test-home"),
            "HOME": str(APP_PATH.parent / "offline-test-home"),
            "AZURE_APPCONFIG_ENDPOINT": "https://production.invalid",
            "AZURE_APPCONFIG_DRAFT_ENDPOINT": "https://draft.invalid",
            "AZURE_OPENAI_ENDPOINT": "https://model.invalid",
            "AZURE_OPENAI_DEPLOYMENT": "offline-deployment",
            "AZURE_SEARCH_ENDPOINT": "https://search.invalid",
            "A2A_AGENT_URL": "https://agent.invalid",
            "ELV_HOSTING_MODE": "development",
            "ELV_AUDIT_BACKEND": "blob",
        }, clear=True))

        # Avoid framework telemetry/machine-ID persistence even when another
        # test has already caused Streamlit to cache its configuration.
        get_option = st.config.get_option
        self.mock(st.config, "get_option", side_effect=lambda name: (
            False if name == "browser.gatherUsageStats" else get_option(name)
        ))

        # Do not import real textstat: some versions acquire NLTK data lazily.
        # Restore only this module entry, not all lazily imported dependencies.
        textstat = ModuleType("textstat")
        for name, value in (("lexicon_count", 8), ("sentence_count", 1),
                            ("flesch_reading_ease", 70), ("text_standard", "Grade 6")):
            setattr(textstat, name, Mock(return_value=value))
        previous = sys.modules.get("textstat")
        sys.modules["textstat"] = textstat
        if previous is None:
            self.stack.callback(sys.modules.pop, "textstat", None)
        else:
            self.stack.callback(sys.modules.__setitem__, "textstat", previous)

        self.guards = {}
        # Guard raw socket connections too, but allow the stdlib's local
        # socketpair implementation, which AppTest's Windows event loop uses.
        pair_scope = threading.local()
        socketpair = socket.socketpair

        def local_socketpair(*args, **kwargs):
            previous = getattr(pair_scope, "active", False)
            pair_scope.active = True
            try:
                return socketpair(*args, **kwargs)
            finally:
                pair_scope.active = previous

        self.stack.enter_context(patch.object(socket, "socketpair", local_socketpair))
        for name in ("connect", "connect_ex"):
            guard = Mock(side_effect=AssertionError("Forbidden raw socket connection"))
            original = getattr(socket.socket, name)

            def connect(sock, address, _original=original, _guard=guard):
                if getattr(pair_scope, "active", False):
                    return _original(sock, address)
                return _guard(address)

            self.stack.enter_context(patch.object(socket.socket, name, connect))
            self.guards[f"socket.socket.{name}"] = guard

        for target in (
            "socket.create_connection", "socket.getaddrinfo",
            "http.client.HTTPConnection.connect", "http.client.HTTPSConnection.connect",
            "requests.sessions.Session.request", "requests.sessions.Session.send",
            "httpx.Client.request", "httpx.Client.send",
            "httpx.AsyncClient.request", "httpx.AsyncClient.send",
            "urllib.request.urlopen", "subprocess.Popen", "os.system",
            "hosting.load_dotenv", "hosting.ManagedIdentityCredential",
            "hosting.audit_resource_ids", "rbac._roles_file",
            "rbac.credential_for", "rbac.service_credential", "rbac.audit_writer_credential",
            "rbac.DefaultAzureCredential", "rbac.ClientSecretCredential",
            "config._client", "config.AzureAppConfigurationClient",
            "knowledge._client", "knowledge.SearchClient", "knowledge.search",
            "prompt._load_asset", "prompt._aoai_client", "prompt.AzureOpenAI",
            "prompt.generate_response", "change_history._container",
            "change_history.ContainerClient", "change_history.record_event",
            "audit.LogsQueryClient", "audit.workspace_configured", "audit.run_query",
            "a2a_client.A2ACardResolver", "a2a_client.create_client",
        ):
            guard = Mock(name=target, side_effect=AssertionError(f"Forbidden external call: {target}"))
            # Explicit Mock also makes an accidental async call fail immediately,
            # rather than leaving an unawaited coroutine hiding a missed patch.
            self.stack.enter_context(patch(target, new=guard))
            self.guards[target] = guard
        self.search = self.guards["knowledge.search"]
        self.file_guard = Mock(side_effect=AssertionError("Forbidden application file access"))
        self.guards["application files"] = self.file_guard
        for module in (builtins, io):
            self.stack.enter_context(patch.object(module, "open", self._guarded_open(module.open)))

        self.load_environment = self.mock(hosting, "load_environment", return_value=None)
        self.mock(rbac, "personas_configured", return_value=True)
        self.mock(rbac, "credential_warnings", return_value=[])
        self.mock(rbac, "display_name", side_effect=lambda persona: f"Offline identity ({persona})")

        profile = {
            "tone": "warm", "verbosity": "concise", "reading_level": "plain language",
            "response_structure": "numbered steps",
            "persona": "a Contoso Health Plan member support agent", "prompt_asset": "response:v2",
        }
        self.profiles = {
            ("baseline", "production"): {**profile, "prompt_asset": "response:v1"},
            ("candidate", "production"): dict(profile),
            ("candidate", "draft"): dict(profile),
        }
        self.scopes = {
            ("candidate", "production"): dict(DEFAULTS),
            ("candidate", "draft"): dict(DEFAULTS),
        }
        # app.py imports load_profile by value; patch config before execution,
        # not an unrelated imported app module or a previous script namespace.
        self.load_profile = self.mock(cfg, "load_profile", side_effect=self._load_profile)
        self.load_knowledge = self.mock(cfg, "load_knowledge", side_effect=self._load_knowledge)
        self.save_experience = self.mock(cfg, "set_value", return_value=cfg.MutationResult())
        self.save_search = self.mock(cfg, "save_knowledge", return_value=cfg.MutationResult())
        self.publish = self.mock(cfg, "publish_draft", return_value=cfg.MutationResult())
        self.probe = self.mock(cfg, "probe", return_value=[])
        self.run_grounded = self.mock(
            experience_runtime, "run_grounded", side_effect=lambda *args: preview_bundle(),
        )
        self.generate = self.mock(
            experience_runtime, "generate_response", side_effect=lambda *args: model_result(),
        )
        self.agent = Mock(spec=a2a_client.ConfiguredAgentClient)
        self.agent.invoke.side_effect = self._invoke_agent
        self.agent_factory = self.mock(a2a_client, "ConfiguredAgentClient", return_value=self.agent)
        self.load_history = self.mock(change_history, "load_events", return_value=change_history.HistoryPage())
        self.export_csv = self.mock(change_history, "export_csv", wraps=change_history.export_csv)
        # AppTest support for download buttons varies by Streamlit version.
        # Capture the exact bytes supplied by the real app, without a download.
        self.download = self.mock(st, "download_button", return_value=False)

        self.clear_caches()
        self.stack.callback(self.clear_caches)

    def tearDown(self):
        # Some production boundaries intentionally catch Exception. A swallowed
        # guard must still fail the test instead of masquerading as an outage.
        for name, guard in self.guards.items():
            with self.subTest(tripwire=name):
                guard.assert_not_called()

    def mock(self, module, name, **kwargs):
        return self.stack.enter_context(patch.object(module, name, **kwargs))

    def _guarded_open(self, original):
        def guarded(file, mode="r", *args, **kwargs):
            name = (os.fsdecode(file).replace("\\", "/").rsplit("/", 1)[-1].lower()
                    if isinstance(file, (str, bytes, os.PathLike)) else "")
            if (any(flag in mode for flag in "wax+") or name == ".env"
                    or name.startswith(".env.") or name in {"roles.local.json", "feedback.csv"}
                    or name.endswith(".prompty")):
                return self.file_guard(file, mode, *args, **kwargs)
            return original(file, mode, *args, **kwargs)
        return guarded

    @staticmethod
    def clear_caches():
        st.cache_data.clear()
        st.cache_resource.clear()

    def _load_profile(self, label, store="production", persona=None):
        return deepcopy(self.profiles[(label, store)])

    def _load_knowledge(self, label="candidate", store="production", persona=None):
        return deepcopy(self.scopes[(label, store)])

    @staticmethod
    def _invoke_agent(message, profile_slot, grounded=False, context_id=None):
        return {
            "task_id": f"task-{profile_slot}", "context_id": f"context-{profile_slot}",
            "profile_slot": profile_slot, "configuration_revision": "offline-revision",
            "prompt_asset": "response:v1" if profile_slot == "baseline" else "response:v2",
            "result": model_result(),
        }

    def start_app(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=15)
        app.secrets = {"offline_test": True}
        return self.run_app(app)

    def run_app(self, app):
        app.run()
        self.assertEqual(len(app.exception), 0, [item.message for item in app.exception])
        return app

    def widget(self, app, kind, label):
        matches = [item for item in getattr(app, kind) if item.label == label]
        self.assertEqual(len(matches), 1, f"Expected one {kind} labelled {label!r}")
        return matches[0]

    def click(self, app, label):
        self.widget(app, "button", label).click()
        return self.run_app(app)

    @staticmethod
    def text(app, kind):
        return "\n".join(item.value for item in getattr(app, kind))

    def assert_no_writes(self):
        for operation in (self.save_experience, self.save_search, self.publish, self.probe):
            operation.assert_not_called()

    def assert_search_controls(self, app, *, disabled):
        for key, (kind, label, value) in SEARCH_CONTROLS.items():
            with self.subTest(field=key):
                control = self.widget(app, kind, label)
                self.assertEqual(control.value, value)
                self.assertEqual(control.disabled, disabled)
                self.assertTrue(control.key.startswith("designer:draft:candidate:"))
                self.assertTrue(control.key.endswith(f":search:{key}"))
                self.assertIn(f"knowledge:{key} — Not stored", self.text(app, "caption"))
        self.assertEqual(self.widget(app, "button", "Save Search settings").disabled, disabled)

    def seed_ui_results(self, app):
        """Valid renderable old results, not sentinels that crash before a button."""
        app.session_state["results"] = {
            "message": DEFAULT_QUESTION,
            "baseline_profile": dict(self.profiles[("baseline", "production")]),
            "candidate_profile": dict(self.profiles[("candidate", "production")]),
            "baseline": model_result(), "candidate": model_result(),
        }
        app.session_state["knowledge_results"] = {
            "question": DEFAULT_QUESTION, "live_scope": dict(DEFAULTS),
            "proposed_scope": dict(DEFAULTS), "live": preview_bundle(), "proposed": preview_bundle(),
        }
        app.session_state["a2a_baseline_context_id"] = "old-baseline"
        app.session_state["a2a_candidate_context_id"] = "old-candidate"
        app.session_state["history_page"] = (24, "2026-09-21T10:00:00+00:00", change_history.HistoryPage())
        app.session_state["unrelated"] = "keep"

    def test_missing_draft_keeps_all_six_search_controls_visible_read_only(self):
        os.environ.pop("AZURE_APPCONFIG_DRAFT_ENDPOINT")
        app = self.start_app()
        self.assert_search_controls(app, disabled=True)
        self.assertIn("defaults, not production values", self.text(app, "info"))
        self.assertNotIn("Save to draft", [button.label for button in app.button])
        self.run_app(app)
        self.load_profile.assert_not_called()
        self.load_knowledge.assert_not_called()
        self.assert_no_writes()

    def test_unseeded_draft_keeps_all_six_controls_editable_without_implicit_writes(self):
        self.profiles[("candidate", "draft")] = {}
        self.scopes[("candidate", "draft")] = {}
        app = self.start_app()
        self.assert_search_controls(app, disabled=False)
        self.assertIn("draft store has no keys", self.text(app, "warning"))
        loads = (self.load_profile.call_count, self.load_knowledge.call_count)
        self.run_app(app)
        self.assertEqual((self.load_profile.call_count, self.load_knowledge.call_count), loads)
        self.assert_no_writes()

    def test_denied_draft_read_shows_all_six_controls_without_enabling_save(self):
        self.load_profile.side_effect = cfg.AccessDenied("read the candidate profile", "draft")
        app = self.start_app()
        self.assert_search_controls(app, disabled=True)
        self.assertIn("Denied by Azure RBAC", self.text(app, "error"))
        self.assertIn("defaults below are not stored values", self.text(app, "caption"))
        self.assert_no_writes()

    def test_experience_uses_same_healthcare_question_and_both_grounding_flags(self):
        app = self.start_app()
        question = "I received a denial notice for my health insurance claim. How can I appeal it?"
        self.assertEqual(DEFAULT_QUESTION, question)
        for label in ("Member message", "Member question"):
            self.assertEqual(self.widget(app, "text_area", label).value, question)
        self.assertTrue(self.widget(app, "checkbox", "Use configured Search grounding").value)
        for grounded in (True, False):
            with self.subTest(grounded=grounded):
                self.agent.invoke.reset_mock()
                self.widget(app, "checkbox", "Use configured Search grounding").set_value(grounded)
                self.click(app, "Generate side-by-side comparison")
                self.assertEqual(self.agent.invoke.call_args_list, [
                    call(question, slot, grounded=grounded,
                         context_id=None if grounded else f"context-{slot}")
                    for slot in ("baseline", "candidate")
                ])
                self.assertEqual(app.session_state["results"]["message"], question)
                for slot in ("baseline", "candidate"):
                    self.assertEqual(app.session_state[f"a2a_{slot}_context_id"], f"context-{slot}")
        self.agent_factory.assert_called_once_with()
        self.run_grounded.assert_not_called()
        self.generate.assert_not_called()
        self.assertEqual(len(app.error), 0)

    def test_disabled_live_and_draft_preview_never_search_even_without_endpoint(self):
        self.run_grounded.side_effect = REAL_RUN_GROUNDED
        self.scopes[("candidate", "production")] = {"enabled": "false"}
        # A missing enabled key is disabled too. Distinct scopes catch the UI
        # accidentally using production settings for both preview columns.
        self.scopes[("candidate", "draft")] = {"index": "draft-index", "top_k": "7"}
        draft_scope = {**DEFAULTS, "index": "draft-index", "top_k": "7"}
        for has_endpoint in (True, False):
            with self.subTest(search_endpoint=has_endpoint):
                if not has_endpoint:
                    os.environ.pop("AZURE_SEARCH_ENDPOINT")
                self.clear_caches()
                self.generate.reset_mock()
                self.run_grounded.reset_mock()
                app = self.start_app()
                self.click(app, "Compare retrieval scopes")
                self.assertEqual(len(app.error), 0)
                self.assertEqual(self.run_grounded.call_count, 2)
                profile = self.profiles[("candidate", "production")]
                self.assertEqual(self.run_grounded.call_args_list, [
                    call(profile, dict(DEFAULTS), DEFAULT_QUESTION, "designer"),
                    call(profile, draft_scope, DEFAULT_QUESTION, "designer"),
                ])
                inputs = {key: value for key, value in profile.items() if key != "prompt_asset"}
                inputs["user_message"] = DEFAULT_QUESTION
                self.assertEqual(self.generate.call_args_list, [call("response:v2", inputs)] * 2)
                for name in ("live", "proposed"):
                    bundle = app.session_state["knowledge_results"][name]
                    self.assertFalse(bundle["grounded"])
                    self.assertEqual(bundle["found"]["documents"], [])
                    self.assertEqual(bundle["found"]["notes"], [experience_runtime.SEARCH_DISABLED_NOTE])
                self.search.assert_not_called()
                if not has_endpoint:
                    self.assertIn("No Search endpoint is configured", self.text(app, "info"))
        self.agent.invoke.assert_not_called()

    def test_experience_save_preserves_confirmed_write_and_history_warning_across_rerun(self):
        result = cfg.MutationResult(changed_keys=["experience:tone"], audit_warnings=[AUDIT_WARNING])

        def save(*args, **kwargs):
            self.profiles[("candidate", "draft")]["tone"] = "empathetic"
            return result

        self.save_experience.side_effect = save
        app = self.start_app()
        self.seed_ui_results(app)
        self.load_profile.reset_mock()
        self.load_knowledge.reset_mock()
        self.widget(app, "text_input", "New value").set_value("empathetic")
        self.click(app, "Save to draft")
        self.save_experience.assert_called_once_with(
            "tone", "empathetic", store="draft", persona="designer", prefix="experience:",
        )
        self.load_profile.assert_any_call("candidate", "draft", "designer")
        self.load_knowledge.assert_any_call("candidate", "draft", "designer")
        for key in ("knowledge_results", "history_page"):
            self.assertNotIn(key, app.session_state)
        self.assertIn("results", app.session_state)
        self.assertEqual(app.session_state["a2a_baseline_context_id"], "old-baseline")
        self.assertEqual(app.session_state["a2a_candidate_context_id"], "old-candidate")
        for _ in range(2):
            self.assertIn("Confirmed writes: experience:tone", self.text(app, "success"))
            self.assertIn(AUDIT_WARNING, self.text(app, "warning"))
            self.assertIsNone(app.session_state["mutation_notice"]["error"])
            self.assertIs(app.session_state["mutation_notice"]["result"], result)
            self.run_app(app)
        self.assertEqual(self.save_experience.call_count, 1, "Audit failure must not retry the write")
        self.save_search.assert_not_called()
        self.publish.assert_not_called()

    def test_search_save_passes_all_six_normalized_values_to_config(self):
        app = self.start_app()
        expression = " \nindustry eq 'healthcare'\n and title eq 'Member ''A''' \t"
        edits = {"enabled": True, "index": " member-index ", "filter": expression,
                 "top_k": 7, "query_mode": "semantic", "citation_style": "footnote"}
        expected = {"enabled": "true", "index": "member-index", "filter": expression.strip(),
                    "top_k": "7", "query_mode": "semantic", "citation_style": "footnote"}
        self.save_search.return_value = cfg.MutationResult(
            changed_keys=[f"knowledge:{key}" for key in expected],
        )
        for key, value in edits.items():
            kind, label, _ = SEARCH_CONTROLS[key]
            self.widget(app, kind, label).set_value(value)
        self.save_search.assert_not_called()
        self.click(app, "Save Search settings")
        self.save_search.assert_called_once_with(expected, persona="designer")
        self.assertEqual(len(app.error), 0)
        self.assertIn("knowledge:query_mode", self.text(app, "success"))
        self.save_experience.assert_not_called()
        self.publish.assert_not_called()
        self.run_app(app)
        self.assertEqual(self.save_search.call_count, 1)

    def test_blank_filter_requires_acknowledgement_before_search_save(self):
        app = self.start_app()
        self.widget(app, "text_area", "OData filter").set_value(" \n\t ")
        self.click(app, "Save Search settings")
        self.assertIn("Tick the explicit acknowledgement", self.text(app, "error"))
        self.assert_no_writes()
        acknowledgement = "I acknowledge that a blank filter applies no filter and may broaden retrieval."
        self.widget(app, "checkbox", acknowledgement).set_value(True)
        self.click(app, "Save Search settings")
        self.save_search.assert_called_once_with({**DEFAULTS, "filter": ""}, persona="designer")
        self.assertEqual(len(app.error), 0)

    def test_partial_publication_invalidates_results_contexts_caches_and_history(self):
        result = cfg.MutationResult(
            changed_keys=["experience:tone"], failed_key="knowledge:filter",
            not_attempted=["knowledge:top_k"], audit_warnings=[AUDIT_WARNING, AUDIT_WARNING],
            outcome="partial",
        )
        failure = cfg.AccessDenied("publish", "production", "private provider detail")
        failure.mutation_result = result

        def partial_publish(*args, **kwargs):
            self.profiles[("candidate", "production")]["tone"] = "partially updated"
            raise failure

        self.publish.side_effect = partial_publish
        app = self.start_app()
        self.widget(app, "radio", "Identity").set_value("approver")
        self.run_app(app)
        self.seed_ui_results(app)
        self.load_profile.reset_mock()
        self.load_knowledge.reset_mock()
        self.click(app, "Publish to production")
        self.publish.assert_called_once_with(persona="approver")
        for key in ("results", "knowledge_results", "history_page",
                    "a2a_baseline_context_id", "a2a_candidate_context_id"):
            self.assertNotIn(key, app.session_state)
        self.assertEqual(app.session_state["unrelated"], "keep")
        for loader in (self.load_profile, self.load_knowledge):
            for store in ("draft", "production"):
                loader.assert_any_call("candidate", store, "approver")
        self.assertIn("Confirmed writes: experience:tone", self.text(app, "success"))
        self.assertIn("Stopped at knowledge:filter. Prior writes were not rolled back", self.text(app, "warning"))
        self.assertIn("Not attempted: knowledge:top_k", self.text(app, "caption"))
        self.assertIn("outcome: partial", self.text(app, "caption"))
        self.assertEqual([item.value for item in app.warning].count(AUDIT_WARNING), 1)
        self.assertIn("Azure denied the configuration operation", self.text(app, "error"))
        self.assertNotIn("private provider detail", self.text(app, "error"))
        self.assertIs(app.session_state["mutation_notice"]["result"], result)
        self.run_app(app)
        self.assertEqual(self.publish.call_count, 1)
        self.save_experience.assert_not_called()
        self.save_search.assert_not_called()

    def test_history_refresh_missing_blob_settings_is_unavailable_not_empty_success(self):
        # Exercise the actual missing-settings -> HistoryUnavailable conversion;
        # SDK/credential tripwires prove that it stops before touching Azure.
        self.load_history.side_effect = REAL_LOAD_EVENTS
        self.assertNotIn("ELV_AUDIT_BLOB_ACCOUNT_URL", os.environ)
        self.assertNotIn("ELV_AUDIT_BLOB_CONTAINER", os.environ)
        app = self.start_app()
        self.load_history.assert_not_called()
        app.session_state["history_page"] = (
            24, "stale", change_history.HistoryPage(events=[history_event(1)]),
        )
        self.click(app, "Refresh change history")
        self.load_history.assert_called_once()
        start, end = self.load_history.call_args.args
        self.assertEqual(end - start, dt.timedelta(hours=24))
        self.assertEqual((start.utcoffset(), end.utcoffset()), (dt.timedelta(0), dt.timedelta(0)))
        self.assertIn("Application change history is unavailable", self.text(app, "error"))
        self.assertNotIn("history_page", app.session_state)
        self.assertNotIn("No recorded events match", self.text(app, "info"))
        self.assertEqual(len(app.dataframe), 0)
        self.export_csv.assert_not_called()
        self.download.assert_not_called()

    def test_history_filters_visible_rows_and_captures_csv_bytes_without_refetch(self):
        saved = history_event(1, new_value='\t=synthetic_formula\n"quoted", value')
        summary = history_event(
            2, operation="publish_summary", key=None, old_value=None, new_value=None,
            old_value_known=False, succeeded_keys=["experience:tone"], failed_key=None, not_attempted=[],
        )
        events = [saved, summary, history_event(3, store="draft"),
                  history_event(4, actor_persona="designer"), history_event(5, outcome="denied")]
        warning = "History is partial: this fixture represents a bounded page."
        self.load_history.return_value = change_history.HistoryPage(events, [warning], truncated=True)
        app = self.start_app()
        self.click(app, "Refresh change history")
        self.assertEqual(len(app.dataframe[0].value), 5)
        self.assertIn(warning, self.text(app, "warning"))
        for label, value in (("History store", "production"), ("History persona", "approver"),
                             ("History outcome", "success")):
            self.widget(app, "selectbox", label).set_value(value)
        self.export_csv.reset_mock()
        self.download.reset_mock()
        self.run_app(app)
        self.load_history.assert_called_once()
        self.export_csv.assert_called_once_with([saved, summary])
        self.download.assert_called_once()
        self.assertEqual(self.download.call_args.args, ("Download visible history as CSV",))
        payload = self.download.call_args.kwargs
        self.assertEqual(payload["file_name"], "poc001-config-history-partial-selection.csv")
        self.assertEqual(payload["mime"], "text/csv")
        self.assertIsInstance(payload["data"], bytes)
        reader = csv.DictReader(io.StringIO(payload["data"].decode("utf-8-sig")))
        rows = list(reader)
        self.assertEqual(reader.fieldnames, list(change_history.CSV_COLUMNS))
        self.assertEqual([row["event_id"] for row in rows], [saved["event_id"], summary["event_id"]])
        self.assertEqual(rows[0]["new_value"], "'" + saved["new_value"])
        self.assertEqual(rows[1]["succeeded_keys"], "experience:tone")
        displayed = app.dataframe[0].value.to_dict("records")
        self.assertEqual([row["operation"] for row in displayed], ["save", "publish_summary"])
        self.assertEqual(displayed[0]["new_value"], saved["new_value"])
        self.assertIn("Publication details", [item.label for item in app.expander])
        self.assertIn("excludes direct Portal/CLI/seed changes", self.text(app, "markdown"))

        # Changing the window must not silently keep/export the previous page.
        self.download.reset_mock()
        self.widget(app, "number_input", "History window (hours, UTC)").set_value(48)
        self.run_app(app)
        self.assertIn("Refresh to apply the changed time window", self.text(app, "info"))
        self.load_history.assert_called_once()
        self.download.assert_not_called()

    def test_blob_mode_ignores_legacy_audit_selection_and_needs_no_resource_ids(self):
        os.environ["ELV_HOSTING_MODE"] = "azure-vm"
        for name in ("AZURE_LOG_ANALYTICS_WORKSPACE_ID", "AZURE_APPCONFIG_RESOURCE_ID",
                     "AZURE_APPCONFIG_DRAFT_RESOURCE_ID"):
            self.assertNotIn(name, os.environ)
        app = self.start_app()
        app.session_state["audit"] = ("Stale legacy selection", audit.CHANGES_QUERY)
        self.click(app, "Refresh change history")
        self.assertEqual(len(app.error), 0)
        self.assertIn("Application-recorded change history", self.text(app, "markdown"))
        self.assertIn("No recorded events match", self.text(app, "info"))
        self.assertNotIn("Who changed what", [button.label for button in app.button])
        for target in ("audit.workspace_configured", "audit.run_query", "audit.LogsQueryClient",
                       "hosting.audit_resource_ids", "rbac.service_credential"):
            self.guards[target].assert_not_called()
        self.assertGreater(self.load_environment.call_count, 0)
        self.assert_no_writes()


if __name__ == "__main__":
    unittest.main()