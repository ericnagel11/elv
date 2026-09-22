import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import audit
import config as cfg
import hosting
import prompt
import rbac
import streamlit as st
from streamlit.testing.v1 import AppTest


RUNTIME_ID = "00000000-0000-4000-8000-000000000001"
COMPARISON_ENV = {
    "ELV_HOSTING_MODE": "azure-vm",
    "ELV_DEMO_MODE": "comparison",
    "ELV_MI_APP_CLIENT_ID": RUNTIME_ID,
}


class ComparisonCredentialTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, COMPARISON_ENV, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_single_runtime_identity_never_uses_legacy_credentials(self):
        with patch.object(rbac, "ManagedIdentityCredential") as credential, \
                patch.object(rbac, "_roles_file", side_effect=AssertionError("legacy file")), \
                patch.object(rbac, "DefaultAzureCredential", side_effect=AssertionError("fallback")), \
                patch.object(rbac, "ClientSecretCredential", side_effect=AssertionError("secret")):
            self.assertIs(rbac.credential_for("app"), credential.return_value)
            self.assertIs(rbac.service_credential("runtime"), credential.return_value)
            self.assertEqual(credential.call_count, 2)
            credential.assert_called_with(client_id=RUNTIME_ID)

    def test_other_personas_and_audit_fail_before_credential_creation(self):
        with patch.object(rbac, "ManagedIdentityCredential") as credential:
            for persona in ("viewer", "designer", "approver", "audit", None):
                with self.subTest(persona=persona), self.assertRaises(rbac.OperationDisabled):
                    rbac.credential_for(persona)
            with self.assertRaises(rbac.OperationDisabled):
                rbac.service_credential("audit")
            credential.assert_not_called()

    def test_missing_malformed_and_zero_runtime_id_fail_closed(self):
        with patch.object(rbac, "ManagedIdentityCredential") as credential:
            for value in ("", "not-a-uuid", "00000000-0000-0000-0000-000000000000"):
                with self.subTest(value=value), patch.dict(os.environ, {"ELV_MI_APP_CLIENT_ID": value}):
                    with self.assertRaisesRegex(ValueError, "ELV_MI_APP_CLIENT_ID"):
                        rbac.service_credential("runtime")
            os.environ.pop("ELV_MI_APP_CLIENT_ID")
            with self.assertRaisesRegex(ValueError, "ELV_MI_APP_CLIENT_ID"):
                rbac.service_credential("runtime")
            credential.assert_not_called()

    def test_comparison_does_not_claim_configured_personas(self):
        self.assertFalse(rbac.personas_configured())
        self.assertEqual(rbac.credential_warnings(), [])
        self.assertEqual(rbac.display_name("app"), "Managed identity (comparison runtime)")
        with self.assertRaises(rbac.OperationDisabled):
            rbac.role_rows("app")

    def test_invalid_modes_and_development_comparison_fail_closed(self):
        with patch.dict(os.environ, {"ELV_DEMO_MODE": "typo"}):
            with self.assertRaisesRegex(ValueError, "ELV_DEMO_MODE"):
                rbac.credential_for("app")
        with patch.dict(os.environ, {"ELV_HOSTING_MODE": "development"}):
            with self.assertRaisesRegex(ValueError, "azure-vm"):
                rbac.credential_for("app")

    def test_default_full_mode_still_requires_five_distinct_identities(self):
        os.environ.pop("ELV_DEMO_MODE")
        with patch.object(hosting, "ManagedIdentityCredential") as credential:
            with self.assertRaisesRegex(ValueError, "ELV_MI_VIEWER_CLIENT_ID"):
                rbac.service_credential("runtime")
            credential.assert_not_called()
            for position, name in enumerate([*rbac.PERSONAS, "audit"], start=1):
                os.environ[f"ELV_MI_{name.upper()}_CLIENT_ID"] = (
                    f"00000000-0000-4000-8000-{position:012d}"
                )
            self.assertTrue(rbac.personas_configured())
            rbac.service_credential("runtime")
            credential.assert_called_once_with(client_id=os.environ["ELV_MI_APP_CLIENT_ID"])
            os.environ["ELV_MI_APP_CLIENT_ID"] = os.environ["ELV_MI_VIEWER_CLIENT_ID"]
            with self.assertRaisesRegex(ValueError, "must not reuse"):
                rbac.service_credential("runtime")


class ComparisonOperationTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, COMPARISON_ENV, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_writes_and_permission_probes_fail_before_reads_or_clients(self):
        operations = (
            lambda: cfg.set_value("tone", "warm", persona="app"),
            lambda: cfg.publish_draft("app"),
            lambda: cfg._rewrite_first_value("production", "baseline", "app"),
            lambda: cfg.probe("app"),
        )
        with patch.object(cfg, "_client") as client, patch.object(cfg, "load_profile") as loader:
            for operation in operations:
                with self.subTest(operation=operation), self.assertRaises(rbac.OperationDisabled):
                    operation()
            client.assert_not_called()
            loader.assert_not_called()

    def test_only_production_experience_profiles_are_read(self):
        with patch.object(cfg, "_client") as client:
            client.return_value.list_configuration_settings.return_value = [
                SimpleNamespace(key="experience:tone", value="warm")
            ]
            for label in cfg.PROFILE_LABELS:
                self.assertEqual(cfg.load_profile(label, persona="app"), {"tone": "warm"})
                client.assert_called_with("production", "app")
                client.return_value.list_configuration_settings.assert_called_with(
                    key_filter="experience:*", label_filter=label
                )

    def test_draft_other_labels_and_knowledge_fail_before_client_creation(self):
        with patch.object(cfg, "_client") as client:
            for arguments in (
                ("candidate", "draft", "app"),
                ("unrelated", "production", "app"),
                ("baseline", "production", "approver"),
                ("baseline", "production", "app", cfg.KNOWLEDGE_PREFIX),
            ):
                with self.subTest(arguments=arguments), self.assertRaises(rbac.OperationDisabled):
                    cfg.load_profile(*arguments)
            with self.assertRaises(rbac.OperationDisabled):
                cfg.load_knowledge(persona="app")
            client.assert_not_called()

    def test_audit_is_unavailable_even_with_workspace_configuration(self):
        os.environ[audit.WORKSPACE_ENV] = RUNTIME_ID
        self.assertFalse(audit.workspace_configured())
        with patch.object(audit, "LogsQueryClient") as client, \
                patch.object(rbac, "service_credential") as credential:
            with self.assertRaises(rbac.OperationDisabled):
                audit.run_query(audit.CHANGES_QUERY)
            credential.assert_not_called()
            client.assert_not_called()


class OpenAIRequestProfileTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"AZURE_OPENAI_DEPLOYMENT": "existing-deployment"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    @patch.object(prompt, "_aoai_client")
    def test_gpt4o_omits_reasoning_controls_for_both_existing_assets(self, client):
        os.environ["ELV_OPENAI_REQUEST_PROFILE"] = "gpt4o"
        client.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Example reply"), finish_reason="stop")],
            usage=None,
        )
        for asset in ("response:v1", "response:v2"):
            with self.subTest(asset=asset):
                result = prompt.generate_response(asset, {"user_message": "Synthetic question"})
                arguments = client.return_value.chat.completions.create.call_args.kwargs
                self.assertEqual(set(arguments), {"model", "messages", "max_tokens"})
                self.assertEqual(arguments["max_tokens"], 3000)
                self.assertEqual(arguments["model"], "existing-deployment")
                self.assertEqual(result["text"], "Example reply")

    def test_default_asset_request_preserves_reasoning_model_parameters(self):
        self.assertEqual(
            prompt.completion_parameters({"max_completion_tokens": 1234, "reasoning_effort": "low"}),
            {"extra_body": {"max_completion_tokens": 1234, "reasoning_effort": "low"}},
        )

    @patch.object(prompt, "_aoai_client")
    def test_invalid_request_profile_fails_before_model_client_creation(self, client):
        os.environ["ELV_OPENAI_REQUEST_PROFILE"] = "typo"
        with self.assertRaisesRegex(ValueError, "ELV_OPENAI_REQUEST_PROFILE"):
            prompt.generate_response("response:v1", {"user_message": "Synthetic question"})
        client.assert_not_called()


class ComparisonUITests(unittest.TestCase):
    def setUp(self):
        home = self.enterContext(tempfile.TemporaryDirectory())
        environment = patch.dict(os.environ, {
            **COMPARISON_ENV,
            "AZURE_APPCONFIG_ENDPOINT": "https://example.azconfig.io",
            "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
            "AZURE_OPENAI_DEPLOYMENT": "example-deployment",
            "USERPROFILE": home,
            "HOME": home,
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        st.cache_data.clear()
        st.cache_resource.clear()
        self.addCleanup(st.cache_data.clear)
        self.addCleanup(st.cache_resource.clear)

    def app(self):
        return AppTest.from_file(
            str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=10
        )

    @staticmethod
    def click(app, label):
        return next(button for button in app.button if button.label == label).click().run()

    def test_only_comparison_ui_executes(self):
        with patch.object(rbac, "personas_configured", side_effect=AssertionError("personas")), \
                patch.object(audit, "workspace_configured", side_effect=AssertionError("audit")), \
                patch("knowledge.configured", side_effect=AssertionError("knowledge")), \
                patch.object(cfg, "load_profile", side_effect=AssertionError("premature read")):
            app = self.app().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertEqual(len(app.radio), 0)
            self.assertEqual(len(app.tabs), 0)
            self.assertEqual(
                {button.label for button in app.button},
                {"Generate side-by-side comparison", "Refresh configuration from Azure"},
            )

    def test_vm_uses_the_healthcare_question_with_and_without_search(self):
        os.environ.update({"ELV_ENABLE_RAG": "true", "ELV_SEARCH_ALLOWED_INDEXES": "medical-policies-vector"})
        with patch("a2a_client.ConfiguredAgentClient") as client:
            app = self.app().run()
            message = next(field for field in app.text_area if field.label == "Member message")
            self.assertEqual(message.value, "I received a denial notice for my health insurance claim. How can I appeal it?")
            app.toggle(key="use_search_grounding").set_value(True).run()
            self.assertFalse(app.exception)
            self.assertEqual(next(field for field in app.text_area if field.label == "Member message").value, message.value)
            client.assert_not_called()

    def test_empty_profiles_report_preparation_gap_without_model_call(self):
        with patch.object(cfg, "load_profile", return_value={}), \
                patch("a2a_client.ConfiguredAgentClient") as client:
            app = self.app().run()
            self.click(app, "Generate side-by-side comparison")
            self.assertFalse(app.exception)
            self.assertIn("baseline and candidate profiles", app.error[0].value)
            client.assert_not_called()

    def test_comparison_results_feedback_and_refresh(self):
        def response(message, profile_slot, context_id=None):
            return {
                "result": {"text": f"Synthetic {profile_slot} response.", "messages": [], "latency_s": 0.1},
                "context_id": f"context-{profile_slot}",
                "task_id": f"task-{profile_slot}",
                "profile_slot": profile_slot,
                "configuration_revision": "revision-1",
                "prompt_asset": "response:v1",
            }

        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"ELV_STATE_DIRECTORY": directory}), \
                patch.object(cfg, "load_profile", return_value={"tone": "warm", "prompt_asset": "response:v1"}), \
                patch("a2a_client.ConfiguredAgentClient") as client, \
                patch("textstat.flesch_reading_ease", return_value=80), \
                patch("textstat.text_standard", return_value="6th grade"):
            client.return_value.invoke.side_effect = response
            app = self.app().run()
            self.click(app, "Generate side-by-side comparison")
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["a2a_baseline_context_id"], "context-baseline")
            self.assertEqual(app.session_state["a2a_candidate_context_id"], "context-candidate")
            self.assertEqual(client.return_value.invoke.call_count, 2)
            self.click(app, "Candidate is better")
            self.assertFalse(app.exception)
            self.assertTrue((Path(directory) / "feedback.csv").is_file())
            self.click(app, "Refresh configuration from Azure")
            self.assertFalse(app.exception)
            self.assertNotIn("results", app.session_state)
            self.assertNotIn("a2a_baseline_context_id", app.session_state)
            self.assertNotIn("a2a_candidate_context_id", app.session_state)
            self.click(app, "Generate side-by-side comparison")
            self.assertFalse(app.exception)
            self.assertEqual(client.return_value.invoke.call_count, 4)
            self.assertIsNone(client.return_value.invoke.call_args.kwargs["context_id"])


    def test_editor_tab_is_opt_in_and_loads_only_on_request(self):
        os.environ["ELV_ENABLE_CONFIG_EDITING"] = "true"
        with patch.object(cfg, "load_editable_setting", return_value={"value": "neutral", "etag": "v1"}) as loader, \
                patch.object(cfg, "update_experience_setting") as updater, \
                patch.object(audit, "workspace_configured", side_effect=AssertionError("audit")), \
                patch("knowledge.configured", side_effect=AssertionError("knowledge")):
            app = self.app().run()
            self.assertFalse(app.exception)
            self.assertEqual([tab.label for tab in app.tabs], ["Experience comparison", "Configuration"])
            self.assertEqual(len(app.radio), 0)
            loader.assert_not_called()
            updater.assert_not_called()
            self.click(app, "Load current value")
            self.assertFalse(app.exception)
            loader.assert_called_once_with("candidate", "tone")
            self.assertEqual(next(field for field in app.text_area if field.label == "New value").value, "neutral")
            updater.assert_not_called()

    def test_successful_editor_save_clears_previous_results_and_contexts(self):
        os.environ["ELV_ENABLE_CONFIG_EDITING"] = "true"
        with patch.object(cfg, "load_editable_setting", return_value={"value": "neutral", "etag": "v1"}), \
                patch.object(cfg, "update_experience_setting", return_value={"value": "warm", "etag": "v2"}) as updater:
            app = self.app().run()
            self.click(app, "Load current value")
            app.session_state["a2a_baseline_context_id"] = "previous-baseline"
            app.session_state["a2a_candidate_context_id"] = "previous-candidate"
            app.session_state["results"] = {}
            next(field for field in app.text_area if field.label == "New value").set_value("warm")
            self.click(app, "Save to Azure")
            self.assertFalse(app.exception)
            updater.assert_called_once_with(label="candidate", short_key="tone", value="warm", expected_etag="v1")
            self.assertIn("candidate / experience:tone", app.success[0].value)
            self.assertEqual(app.session_state["live_config_loaded"]["etag"], "v2")
            for key in ("results", "a2a_baseline_context_id", "a2a_candidate_context_id"):
                self.assertNotIn(key, app.session_state)

    def test_editor_conflict_preserves_unsaved_value_and_does_not_report_success(self):
        os.environ["ELV_ENABLE_CONFIG_EDITING"] = "true"
        with patch.object(cfg, "load_editable_setting", return_value={"value": "neutral", "etag": "v1"}), \
                patch.object(cfg, "update_experience_setting", side_effect=cfg.ConfigurationConflict("Reload the changed setting.")) as updater:
            app = self.app().run()
            self.click(app, "Load current value")
            next(field for field in app.text_area if field.label == "New value").set_value("warm")
            self.click(app, "Save to Azure")
            self.assertFalse(app.exception)
            self.assertFalse(app.success)
            self.assertTrue(any("Reload" in warning.value for warning in app.warning))
            self.assertEqual(next(field for field in app.text_area if field.label == "New value").value, "warm")
            self.assertEqual(app.session_state["live_config_loaded"]["etag"], "v1")
            self.assertEqual(updater.call_count, 1)

    def test_switching_profile_requires_loading_its_own_value(self):
        os.environ["ELV_ENABLE_CONFIG_EDITING"] = "true"
        with patch.object(cfg, "load_editable_setting", return_value={"value": "neutral", "etag": "v1"}) as loader, \
                patch.object(cfg, "update_experience_setting") as updater:
            app = self.app().run()
            self.click(app, "Load current value")
            app.selectbox(key="live_config_profile").select("baseline").run()
            self.assertFalse(app.exception)
            self.assertNotIn("live_config_loaded", app.session_state)
            self.assertFalse(any(button.label == "Save to Azure" for button in app.button))
            self.click(app, "Load current value")
            loader.assert_called_with("baseline", "tone")
            updater.assert_not_called()

    def test_prompt_asset_uses_supported_options(self):
        os.environ["ELV_ENABLE_CONFIG_EDITING"] = "true"
        with patch.object(cfg, "load_editable_setting", return_value={"value": "response:v2", "etag": "v1"}), \
                patch.object(cfg, "update_experience_setting", return_value={"value": "response:v1", "etag": "v2"}) as updater:
            app = self.app().run()
            app.selectbox(key="live_config_key").select("prompt_asset").run()
            self.click(app, "Load current value")
            selector = next(field for field in app.selectbox if field.label == "Prompt asset")
            self.assertEqual(selector.options, list(cfg.COMPARISON_PROMPT_ASSETS))
            selector.select("response:v1")
            self.click(app, "Save to Azure")
            self.assertFalse(app.exception)
            updater.assert_called_once_with(label="candidate", short_key="prompt_asset", value="response:v1", expected_etag="v1")

    def test_reloading_discards_unsaved_text_even_when_version_is_unchanged(self):
        os.environ["ELV_ENABLE_CONFIG_EDITING"] = "true"
        with patch.object(cfg, "load_editable_setting", return_value={"value": "neutral", "etag": "v1"}) as loader, \
                patch.object(cfg, "update_experience_setting") as updater:
            app = self.app().run()
            self.click(app, "Load current value")
            next(field for field in app.text_area if field.label == "New value").set_value("unsaved edit")
            self.click(app, "Load current value")
            self.assertFalse(app.exception)
            self.assertEqual(next(field for field in app.text_area if field.label == "New value").value, "neutral")
            self.assertEqual(loader.call_count, 2)
            updater.assert_not_called()


    def test_rag_toggle_requests_grounding_and_displays_only_citation_metadata(self):
        os.environ.update({"ELV_ENABLE_RAG": "true", "ELV_SEARCH_ALLOWED_INDEXES": "medical-policies-vector"})

        def response(message, profile_slot, context_id=None, grounded=False):
            self.assertTrue(grounded)
            self.assertIsNone(context_id)
            return {
                "result": {"text": "Synthetic answer [1].", "messages": [], "latency_s": 0.1},
                "context_id": f"rag-{profile_slot}", "task_id": "task-1",
                "profile_slot": profile_slot, "configuration_revision": "revision-1", "prompt_asset": "response:v3",
                "citations": [{"n": 1, "title": "Synthetic policy", "status": "Reviewed", "state": "NY", "source": "example.pdf"}],
            }

        with patch.object(cfg, "load_profile", return_value={"tone": "warm", "prompt_asset": "response:v1"}), \
                patch("a2a_client.ConfiguredAgentClient") as client, \
                patch("textstat.flesch_reading_ease", return_value=80), \
                patch("textstat.text_standard", return_value="6th grade"):
            client.return_value.invoke.side_effect = response
            app = self.app().run()
            app.session_state["a2a_baseline_context_id"] = "old-baseline"
            app.session_state["a2a_candidate_context_id"] = "old-candidate"
            app.toggle(key="use_search_grounding").set_value(True).run()
            self.click(app, "Generate side-by-side comparison")
            self.assertFalse(app.exception)
            self.assertEqual(client.return_value.invoke.call_count, 2)
            self.assertEqual(sum(expander.label == "Sources (1)" for expander in app.expander), 2)
            self.assertEqual(app.session_state["results"]["candidate"]["citations"][0]["state"], "NY")
            app.toggle(key="use_search_grounding").set_value(False).run()
            self.assertNotIn("results", app.session_state)
            self.assertNotIn("a2a_candidate_context_id", app.session_state)

    def test_knowledge_editor_saves_blank_filter_only_on_explicit_save(self):
        os.environ.update({
            "ELV_ENABLE_RAG": "true", "ELV_SEARCH_ALLOWED_INDEXES": "medical-policies-vector",
            "ELV_ENABLE_CONFIG_EDITING": "true",
        })
        with patch.object(cfg, "load_editable_setting", return_value={"value": "State eq 'NY'", "etag": "v1"}) as loader, \
                patch.object(cfg, "update_knowledge_setting", return_value={"value": "", "etag": "v2"}) as updater:
            app = self.app().run()
            app.selectbox(key="live_config_area").select("Knowledge").run()
            app.selectbox(key="live_config_key").select("filter").run()
            loader.assert_not_called()
            self.click(app, "Load current value")
            loader.assert_called_once_with("candidate", "filter", prefix="knowledge:")
            updater.assert_not_called()
            next(field for field in app.text_area if field.label == "New value").set_value("")
            self.click(app, "Save to Azure")
            updater.assert_not_called()
            self.assertTrue(any("acknowledgement" in item.value for item in app.error))
            next(field for field in app.checkbox if field.label.startswith("I acknowledge")).set_value(True)
            self.click(app, "Save to Azure")
            self.assertFalse(app.exception)
            updater.assert_called_once_with(label="candidate", short_key="filter", value="", expected_etag="v1")
            self.assertIn("knowledge:filter", app.success[0].value)

    def test_knowledge_index_control_offers_only_vm_approved_indexes(self):
        os.environ.update({
            "ELV_ENABLE_RAG": "true", "ELV_SEARCH_ALLOWED_INDEXES": "medical-policies-vector",
            "ELV_ENABLE_CONFIG_EDITING": "true",
        })
        with patch.object(cfg, "load_editable_setting", return_value={"value": "medical-policies-vector", "etag": "v1"}), \
                patch.object(cfg, "update_knowledge_setting") as updater:
            app = self.app().run()
            app.selectbox(key="live_config_area").select("Knowledge").run()
            app.selectbox(key="live_config_key").select("index").run()
            self.click(app, "Load current value")
            self.assertFalse(app.exception)
            selector = next(field for field in app.selectbox if field.label == "New value")
            self.assertEqual(selector.options, ["medical-policies-vector"])
            updater.assert_not_called()

    @staticmethod
    def live_search_snapshot():
        settings = {"enabled": "true", "index": "medical-policies-vector", "filter": "",
                    "top_k": "3", "query_mode": "simple", "citation_style": "inline"}
        return {"settings": settings, "etags": {key: f"version-{key}" for key in settings}}

    def enable_knowledge_editor(self):
        os.environ.update({
            "ELV_ENABLE_RAG": "true", "ELV_SEARCH_ALLOWED_INDEXES": "medical-policies-vector",
            "ELV_ENABLE_CONFIG_EDITING": "true",
        })
        app = self.app().run()
        app.selectbox(key="live_config_area").select("Knowledge").run()
        return app

    def test_grouped_vm_search_form_loads_on_request_and_preserves_stored_blank_filter(self):
        snapshot = self.live_search_snapshot()
        with patch.object(cfg, "load_live_knowledge", return_value=snapshot) as loader, \
                patch.object(cfg, "update_live_knowledge") as updater:
            app = self.enable_knowledge_editor()
            loader.assert_not_called()
            self.click(app, "Load Search settings")
            self.assertFalse(app.exception)
            loader.assert_called_once_with("candidate")
            self.assertEqual(next(field for field in app.text_area if field.label == "OData filter").value, "")
            self.assertEqual(next(field for field in app.selectbox if field.label == "Query mode").options, ["simple"])
            self.assertEqual(next(field for field in app.selectbox if field.label == "Search index or alias").options, ["medical-policies-vector"])
            updater.assert_not_called()
            self.click(app, "Save Search settings")
            updater.assert_not_called()
            self.assertTrue(any("acknowledgement" in item.value for item in app.error))
            app.selectbox(key="live_config_profile").select("baseline").run()
            self.assertNotIn("live_search_loaded", app.session_state)
            self.assertFalse(any(button.label == "Save Search settings" for button in app.button))

    def test_grouped_vm_search_save_uses_loaded_etags_and_clears_contexts(self):
        snapshot = self.live_search_snapshot()
        result = cfg.MutationResult(changed_keys=["knowledge:filter", "knowledge:top_k"])
        with patch.object(cfg, "load_live_knowledge", return_value=snapshot), \
                patch.object(cfg, "update_live_knowledge", return_value=result) as updater:
            app = self.enable_knowledge_editor()
            self.click(app, "Load Search settings")
            next(field for field in app.text_area if field.label == "OData filter").set_value("State eq 'NY'")
            next(field for field in app.number_input if field.label == "Top documents (top_k)").set_value(5)
            app.session_state["a2a_baseline_context_id"] = "old-baseline"
            app.session_state["a2a_candidate_context_id"] = "old-candidate"
            app.session_state["results"] = {}
            self.click(app, "Save Search settings")
            self.assertFalse(app.exception)
            updater.assert_called_once_with(
                "candidate", {**snapshot["settings"], "filter": "State eq 'NY'", "top_k": "5"}, snapshot["etags"],
            )
            self.assertTrue(any("knowledge:filter" in item.value for item in app.success))
            for key in ("results", "a2a_baseline_context_id", "a2a_candidate_context_id", "live_search_loaded"):
                self.assertNotIn(key, app.session_state)

    def test_grouped_vm_partial_save_shows_exact_outcome_without_retry(self):
        snapshot = self.live_search_snapshot()
        error = cfg.ConfigurationConflict("Search settings changed. Reload before saving.")
        error.mutation_result = cfg.MutationResult(
            changed_keys=["knowledge:filter"], failed_key="knowledge:top_k",
            not_attempted=["knowledge:query_mode", "knowledge:citation_style"], outcome="partial",
        )
        with patch.object(cfg, "load_live_knowledge", return_value=snapshot), \
                patch.object(cfg, "update_live_knowledge", side_effect=error) as updater:
            app = self.enable_knowledge_editor()
            self.click(app, "Load Search settings")
            next(field for field in app.text_area if field.label == "OData filter").set_value("State eq 'NY'")
            self.click(app, "Save Search settings")
            self.assertFalse(app.exception)
            self.assertTrue(any("Reload" in item.value for item in app.error))
            self.assertTrue(any("knowledge:filter" in item.value for item in app.success))
            self.assertTrue(any("Prior writes were not rolled back" in item.value for item in app.warning))
            self.assertNotIn("live_search_loaded", app.session_state)
            app.run()
            self.assertEqual(updater.call_count, 1)


class WindowsLauncherTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[3] / "deployment" / "windows" / "run.py"
        spec = importlib.util.spec_from_file_location("windows_launcher", path)
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = {
            "AZURE_APPCONFIG_ENDPOINT": "https://example.azconfig.io",
            "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
            "AZURE_OPENAI_DEPLOYMENT": "existing-deployment",
            "AZURE_OPENAI_API_VERSION": "2024-10-21",
            "ELV_MI_APP_CLIENT_ID": RUNTIME_ID,
            "ELV_STATE_DIRECTORY": str(self.directory),
        }

    def test_external_json_requires_only_comparison_settings(self):
        path = self.directory / "runtime.json"
        path.write_text(json.dumps(self.settings), encoding="utf-8-sig")
        self.assertEqual(self.launcher.load_settings(path), self.settings)

    def test_editing_requires_explicit_runtime_json_opt_in(self):
        with patch.dict(os.environ, {"ELV_ENABLE_CONFIG_EDITING": "true"}, clear=True):
            self.assertEqual(self.launcher.process_environment(self.settings)["ELV_ENABLE_CONFIG_EDITING"], "false")
            self.settings["ELV_ENABLE_CONFIG_EDITING"] = "true"
            self.assertEqual(self.launcher.process_environment(self.settings)["ELV_ENABLE_CONFIG_EDITING"], "true")
            self.settings["ELV_ENABLE_CONFIG_EDITING"] = "false"
            self.assertEqual(self.launcher.process_environment(self.settings)["ELV_ENABLE_CONFIG_EDITING"], "false")

    def test_invalid_editing_configuration_is_rejected(self):
        for value in ("yes", "TRUE", "", True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "ELV_ENABLE_CONFIG_EDITING"):
                self.launcher.validate_settings({**self.settings, "ELV_ENABLE_CONFIG_EDITING": value})

    def test_rag_requires_explicit_opt_in_endpoint_and_index_allowlist(self):
        inherited = {"ELV_ENABLE_RAG": "true", "AZURE_SEARCH_ENDPOINT": "https://other.search.windows.net", "ELV_SEARCH_ALLOWED_INDEXES": "other-index"}
        with patch.dict(os.environ, inherited, clear=True):
            environment = self.launcher.process_environment(self.settings)
            self.assertEqual(environment["ELV_ENABLE_RAG"], "false")
            self.assertEqual(environment["ELV_SEARCH_ALLOWED_INDEXES"], "")
            self.assertEqual(environment["AZURE_SEARCH_ENDPOINT"], "")
        settings = {**self.settings, "ELV_ENABLE_RAG": "true"}
        with self.assertRaisesRegex(ValueError, "AZURE_SEARCH_ENDPOINT"):
            self.launcher.validate_settings(settings)
        settings["AZURE_SEARCH_ENDPOINT"] = "https://example.search.windows.net"
        with self.assertRaisesRegex(ValueError, "ELV_SEARCH_ALLOWED_INDEXES"):
            self.launcher.validate_settings(settings)
        settings["ELV_SEARCH_ALLOWED_INDEXES"] = "medical-policies-vector"
        self.launcher.validate_settings(settings)
        for key, value in (("ELV_ENABLE_RAG", "yes"), ("AZURE_SEARCH_ENDPOINT", "http://example.search.windows.net"),
                           ("ELV_SEARCH_ALLOWED_INDEXES", "*"), ("ELV_SEARCH_ALLOWED_INDEXES", "")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.launcher.validate_settings({**settings, key: value})

    def test_json_rejects_duplicates_unknown_keys_and_checkout_paths(self):
        path = self.directory / "runtime.json"
        for text in ('{"repeated":"one","repeated":"two"}', '{"AZURE_CLIENT_SECRET":"not-a-secret"}', '[]'):
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.launcher.load_settings(path)
        with self.assertRaisesRegex(ValueError, "outside the source checkout"):
            self.launcher.load_settings(self.launcher.ROOT / "runtime.json")

    def test_invalid_settings_are_rejected_without_echoing_values(self):
        invalid = (
            ("AZURE_APPCONFIG_ENDPOINT", "http://example.azconfig.io"),
            ("AZURE_OPENAI_ENDPOINT", "https://user:not-a-secret@example.openai.azure.com"),
            ("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/project"),
            ("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com?key=not-a-secret"),
            ("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com:80"),
            ("ELV_MI_APP_CLIENT_ID", "00000000-0000-0000-0000-000000000000"),
            ("AZURE_OPENAI_DEPLOYMENT", "<deployment>"),
            ("AZURE_OPENAI_API_VERSION", "2024-10-21-preview"),
            ("ELV_OPENAI_REQUEST_PROFILE", "asset"),
            ("ELV_STATE_DIRECTORY", "relative-path"),
            ("AZURE_OPENAI_DEPLOYMENT", None),
        )
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError) as error:
                    self.launcher.validate_settings({**self.settings, key: value})
                self.assertNotIn("not-a-secret", str(error.exception))

    def test_inherited_credentials_are_rejected(self):
        for key in ("AZURE_CLIENT_SECRET", "AZURE_CLIENT_CERTIFICATE_PATH", "AZURE_FEDERATED_TOKEN_FILE"):
            with self.subTest(key=key), patch.dict(os.environ, {key: "not-a-secret"}, clear=True):
                with self.assertRaisesRegex(ValueError, key):
                    self.launcher.process_environment(self.settings)

    def test_launcher_forces_policy_and_preserves_proxy_ca_settings(self):
        inherited = {
            "ELV_HOSTING_MODE": "development", "ELV_DEMO_MODE": "full",
            "A2A_AGENT_URL": "http://unapproved", "A2A_AGENT_HOST": "0.0.0.0",
            "NO_PROXY": "existing.internal,another.internal",
            "HTTPS_PROXY": "http://approved-proxy:8080", "REQUESTS_CA_BUNDLE": "approved.pem",
        }
        with patch.dict(os.environ, inherited, clear=True):
            environment = self.launcher.process_environment(self.settings)
            self.assertEqual(os.environ["ELV_DEMO_MODE"], "full")
        for key, value in self.launcher.FORCED_SETTINGS.items():
            self.assertEqual(environment[key], value)
        self.assertEqual(environment["HTTPS_PROXY"], inherited["HTTPS_PROXY"])
        self.assertEqual(environment["REQUESTS_CA_BUNDLE"], "approved.pem")
        self.assertEqual(environment["NO_PROXY"], environment["no_proxy"])
        self.assertEqual(set(environment["NO_PROXY"].split(",")), {
            "existing.internal", "another.internal", "169.254.169.254", "127.0.0.1", "localhost",
        })

    def test_component_commands_keep_both_listeners_on_loopback(self):
        agent = self.launcher.command_for("agent", "python.exe", self.directory)
        self.assertEqual(agent[agent.index("--host") + 1], "127.0.0.1")
        self.assertEqual(agent[agent.index("--port") + 1], "9999")
        ui = self.launcher.command_for("ui", "python.exe", self.directory)
        for flag in (
            "--server.address=127.0.0.1", "--server.port=8501",
            "--server.enableCORS=true", "--server.enableXsrfProtection=true",
            "--browser.gatherUsageStats=false",
        ):
            self.assertIn(flag, ui)
        with self.assertRaises(ValueError):
            self.launcher.command_for("unknown", "python.exe", self.directory)

    def test_validate_only_never_creates_a_credential_or_starts_a_process(self):
        path = self.directory / "runtime.json"
        path.write_text(json.dumps(self.settings), encoding="utf-8")
        python = self.launcher.PROJECT / ".venv" / "Scripts" / "python.exe"
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(self.launcher.sys, "platform", "win32"), \
                patch.object(self.launcher.sys, "executable", str(python)), \
                patch.object(self.launcher.subprocess, "run") as process, \
                patch.object(rbac, "ManagedIdentityCredential") as credential:
            self.assertEqual(self.launcher.main([
                "--component", "agent", "--config", str(path),
                "--approved-azure-host", "--validate-only",
            ]), 0)
            process.assert_not_called()
            credential.assert_not_called()


class ConfigurationInitializerTests(unittest.TestCase):
    def setUp(self):
        directory = Path(__file__).resolve().parents[3] / "deployment" / "windows"
        launcher_spec = importlib.util.spec_from_file_location("run", directory / "run.py")
        launcher = importlib.util.module_from_spec(launcher_spec)
        launcher_spec.loader.exec_module(launcher)
        spec = importlib.util.spec_from_file_location("initializer", directory / "initialize_config.py")
        self.initializer = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"run": launcher}):
            spec.loader.exec_module(self.initializer)
        self.settings = self.initializer.sample_settings()
        state = self.enterContext(tempfile.TemporaryDirectory())
        self.runtime = {
            "AZURE_APPCONFIG_ENDPOINT": "https://example.azconfig.io",
            "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
            "AZURE_OPENAI_DEPLOYMENT": "existing-deployment",
            "AZURE_OPENAI_API_VERSION": "2024-10-21",
            "ELV_MI_APP_CLIENT_ID": RUNTIME_ID,
            "ELV_STATE_DIRECTORY": state,
        }
        self.output = self.enterContext(patch("sys.stdout", new_callable=io.StringIO))
        self.client = Mock()
        self.store = {}

        def get_setting(*, key, label):
            if (key, label) not in self.store:
                raise self.initializer.ResourceNotFoundError()
            return self.store[(key, label)]

        def add_setting(setting):
            target = (setting.key, setting.label)
            if target in self.store:
                raise self.initializer.ResourceExistsError()
            self.store[target] = setting
            return setting

        self.client.get_configuration_setting.side_effect = get_setting
        self.client.add_configuration_setting.side_effect = add_setting

    def test_preview_never_creates_credentials_or_azure_clients(self):
        runtime = {"AZURE_APPCONFIG_ENDPOINT": "https://example.azconfig.io"}
        with patch.object(self.initializer, "load_settings", return_value=runtime), \
                patch.object(self.initializer, "ManagedIdentityCredential") as credential, \
                patch.object(self.initializer, "AzureAppConfigurationClient") as client:
            self.assertEqual(self.initializer.main(["--config", "runtime.json"]), 0)
            self.assertIn("PREVIEW_ONLY", self.output.getvalue())
            self.assertEqual(self.output.getvalue().count("experience:"), 12)
            credential.assert_not_called()
            client.assert_not_called()

    def knowledge_profile(self):
        profile = dict.fromkeys(cfg.COMPARISON_KNOWLEDGE_KEYS, "")
        profile.update({
            "enabled": "true", "index": "medical-policies-vector", "top_k": "3",
            "query_mode": "simple", "citation_style": "inline", "title_field": "Title",
            "content_field": "Content", "status_field": "Status", "state_field": "State",
            "source_field": "BlobName", "effective_date_field": "PublishDate", "search_fields": "Title,Content",
        })
        return profile

    def test_knowledge_preview_contains_only_knowledge_keys_and_makes_no_azure_calls(self):
        runtime = {**self.runtime, "ELV_ENABLE_RAG": "true", "ELV_SEARCH_ALLOWED_INDEXES": "medical-policies-vector"}
        path = Path(self.runtime["ELV_STATE_DIRECTORY"]) / "knowledge.json"
        path.write_text(json.dumps(self.knowledge_profile()), encoding="utf-8")
        with patch.object(self.initializer, "load_settings", return_value=runtime), \
                patch.object(self.initializer, "ManagedIdentityCredential") as credential, \
                patch.object(self.initializer, "AzureAppConfigurationClient") as client:
            self.assertEqual(self.initializer.main(["--config", "runtime.json", "--knowledge-config", str(path)]), 0)
            self.assertIn("32 proposed entries", self.output.getvalue())
            self.assertNotIn("experience:", self.output.getvalue())
            credential.assert_not_called()
            client.assert_not_called()

    def test_knowledge_initialization_reuses_create_only_behavior_without_touching_experience(self):
        runtime = {**self.runtime, "ELV_ENABLE_RAG": "true", "ELV_SEARCH_ALLOWED_INDEXES": "medical-policies-vector"}
        path = Path(self.runtime["ELV_STATE_DIRECTORY"]) / "knowledge.json"
        path.write_text(json.dumps(self.knowledge_profile()), encoding="utf-8")
        settings = self.initializer.knowledge_settings(path, runtime)
        original = cfg.ConfigurationSetting(key="experience:tone", label="candidate", value="customer edit")
        self.store[(original.key, original.label)] = original
        self.assertEqual(self.initializer.initialize(self.client, settings), (32, 0))
        self.assertEqual(self.store[(original.key, original.label)].value, "customer edit")
        self.assertTrue(all(call.args[0].key.startswith("knowledge:") for call in self.client.add_configuration_setting.call_args_list))
        self.client.set_configuration_setting.assert_not_called()
        self.client.delete_configuration_setting.assert_not_called()

    def test_knowledge_profile_requires_opt_in_exact_keys_and_approved_index(self):
        runtime = {**self.runtime, "ELV_ENABLE_RAG": "true", "ELV_SEARCH_ALLOWED_INDEXES": "medical-policies-vector"}
        path = Path(self.runtime["ELV_STATE_DIRECTORY"]) / "knowledge.json"
        profile = self.knowledge_profile()
        path.write_text(json.dumps(profile), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Enable RAG"):
            self.initializer.knowledge_settings(path, self.runtime)
        for invalid in ({**profile, "index": "other-index"}, {**profile, "extra_setting": "not allowed"},
                        {**profile, "query_mode": "vector"}, {**profile, "content_field": ""}):
            with self.subTest(invalid=invalid):
                path.write_text(json.dumps(invalid), encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.initializer.knowledge_settings(path, runtime)

    def test_apply_requires_explicit_approved_host_before_reading_configuration(self):
        with patch.object(self.initializer, "load_settings") as loader, \
                patch.object(self.initializer, "ManagedIdentityCredential") as credential:
            with self.assertRaisesRegex(ValueError, "approved-azure-host"):
                self.initializer.main(["--config", "runtime.json", "--apply"])
            loader.assert_not_called()
            credential.assert_not_called()

    def test_apply_selects_only_the_configured_managed_identity_and_store(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(self.initializer.sys, "platform", "win32"), \
                patch.object(self.initializer, "load_settings", return_value=self.runtime), \
                patch.object(self.initializer, "ManagedIdentityCredential") as credential, \
                patch.object(self.initializer, "AzureAppConfigurationClient") as client:
            client.return_value.__enter__.return_value = self.client
            self.assertEqual(self.initializer.main([
                "--config", "runtime.json", "--apply", "--approved-azure-host",
            ]), 0)
            credential.assert_called_once_with(client_id=RUNTIME_ID)
            client.assert_called_once_with(
                base_url=self.runtime["AZURE_APPCONFIG_ENDPOINT"],
                credential=credential.return_value.__enter__.return_value,
                retry_total=0, connection_timeout=10, read_timeout=30,
            )
            self.assertEqual(len(self.store), 12)
            self.assertIn("INITIALIZATION_SUCCEEDED", self.output.getvalue())

    def test_apply_rejects_inherited_secret_before_creating_a_credential(self):
        with patch.dict(os.environ, {"AZURE_CLIENT_SECRET": "not-a-secret"}, clear=True), \
                patch.object(self.initializer.sys, "platform", "win32"), \
                patch.object(self.initializer, "load_settings", return_value=self.runtime), \
                patch.object(self.initializer, "ManagedIdentityCredential") as credential:
            with self.assertRaisesRegex(ValueError, "AZURE_CLIENT_SECRET"):
                self.initializer.main([
                    "--config", "runtime.json", "--apply", "--approved-azure-host",
                ])
            credential.assert_not_called()

    def test_exactly_twelve_experience_settings_are_created_and_read_back(self):
        self.assertEqual(self.initializer.initialize(self.client, self.settings), (12, 0))
        self.assertEqual(len(self.store), 12)
        self.assertEqual(self.client.add_configuration_setting.call_count, 12)
        self.assertEqual(self.client.get_configuration_setting.call_count, 24)
        self.assertEqual({setting.label for setting in self.settings}, {"baseline", "candidate"})
        self.assertTrue(all(setting.key.startswith("experience:") for setting in self.settings))
        self.client.set_configuration_setting.assert_not_called()
        self.client.delete_configuration_setting.assert_not_called()

    def test_rerun_preserves_matching_entries_without_writes(self):
        self.store.update({(setting.key, setting.label): setting for setting in self.settings})
        self.assertEqual(self.initializer.initialize(self.client, self.settings), (0, 12))
        self.client.add_configuration_setting.assert_not_called()
        self.client.set_configuration_setting.assert_not_called()

    def test_existing_conflict_stops_all_creates_without_disclosing_the_value(self):
        setting = self.settings[-1]
        self.store[(setting.key, setting.label)] = SimpleNamespace(value="private-existing-value")
        with self.assertRaises(self.initializer.InitializationConflict) as error:
            self.initializer.initialize(self.client, self.settings)
        self.assertNotIn("private-existing-value", str(error.exception))
        self.client.add_configuration_setting.assert_not_called()
        self.client.set_configuration_setting.assert_not_called()

    def test_concurrent_create_conflict_is_not_overwritten(self):
        def concurrent_create(setting):
            self.store[(setting.key, setting.label)] = SimpleNamespace(value="another-writer-value")
            raise self.initializer.ResourceExistsError()

        self.client.add_configuration_setting.side_effect = concurrent_create
        with self.assertRaises(self.initializer.InitializationConflict):
            self.initializer.initialize(self.client, self.settings)
        self.assertEqual(self.client.add_configuration_setting.call_count, 1)
        self.client.set_configuration_setting.assert_not_called()
        self.client.delete_configuration_setting.assert_not_called()

    def test_midrun_failure_does_not_delete_previously_created_settings(self):
        add_setting = self.client.add_configuration_setting.side_effect

        def fail_second_create(setting):
            if self.store:
                raise self.initializer.HttpResponseError("synthetic failure")
            return add_setting(setting)

        self.client.add_configuration_setting.side_effect = fail_second_create
        with self.assertRaises(self.initializer.HttpResponseError):
            self.initializer.initialize(self.client, self.settings)
        self.assertEqual(len(self.store), 1)
        self.client.delete_configuration_setting.assert_not_called()


class LiveConfigurationEditTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {
            **COMPARISON_ENV, "ELV_ENABLE_CONFIG_EDITING": "true",
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.client_type = self.enterContext(patch.object(cfg, "_client"))
        self.client = self.client_type.return_value
        self.current = cfg.ConfigurationSetting(
            key="experience:tone", label="candidate", value="neutral",
            etag="version-1", content_type="text/plain", tags={"owner": "demo"},
        )
        self.client.get_configuration_setting.return_value = self.current
        self.client.set_configuration_setting.return_value = cfg.ConfigurationSetting(
            key="experience:tone", label="candidate", value="warm", etag="version-2",
        )

    def test_editor_requires_explicit_opt_in(self):
        os.environ.pop("ELV_ENABLE_CONFIG_EDITING")
        self.assertFalse(rbac.config_editing_enabled())
        with self.assertRaises(rbac.OperationDisabled):
            cfg.load_editable_setting("candidate", "tone")
        with self.assertRaises(rbac.OperationDisabled):
            cfg.update_experience_setting("candidate", "tone", "warm", "version-1")
        self.client_type.assert_not_called()
        os.environ["ELV_ENABLE_CONFIG_EDITING"] = "typo"
        with self.assertRaisesRegex(ValueError, "ELV_ENABLE_CONFIG_EDITING"):
            rbac.config_editing_enabled()

    def test_reads_only_selected_existing_key_and_version(self):
        for label in cfg.PROFILE_LABELS:
            self.assertEqual(cfg.load_editable_setting(label, "tone"), {
                "value": "neutral", "etag": "version-1",
            })
            self.client_type.assert_called_with("production", "app")
            self.client.get_configuration_setting.assert_called_with(key="experience:tone", label=label)
        self.client.set_configuration_setting.assert_not_called()

    def test_save_preserves_metadata_and_requires_the_loaded_version(self):
        result = cfg.update_experience_setting("candidate", "tone", "warm", "version-1")
        self.assertEqual(result, {"value": "warm", "etag": "version-2"})
        self.client_type.assert_called_once_with("production", "app")
        self.client.set_configuration_setting.assert_called_once_with(
            self.current, etag="version-1", match_condition=cfg.MatchConditions.IfNotModified,
        )
        self.assertEqual(self.current.tags, {"owner": "demo"})
        self.assertEqual(self.current.content_type, "text/plain")
        self.assertEqual(self.current.value, "warm")
        self.client.add_configuration_setting.assert_not_called()
        self.client.delete_configuration_setting.assert_not_called()

    def test_other_keys_labels_and_unsafe_values_fail_before_client_creation(self):
        for label, short_key in (("draft", "tone"), ("unrelated", "tone"),
                                 ("candidate", "knowledge:enabled"), ("candidate", "unrelated")):
            with self.subTest(label=label, key=short_key), self.assertRaises(rbac.OperationDisabled):
                cfg.update_experience_setting(label, short_key, "warm", "version-1")
        for value in ("", "  ", "bad\x00value", "a" * (cfg.MAX_EDIT_VALUE_LENGTH + 1)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cfg.update_experience_setting("candidate", "tone", value, "version-1")
        for version in ("", "*", None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                cfg.update_experience_setting("candidate", "tone", "warm", version)
        with self.assertRaises(ValueError):
            cfg.update_experience_setting("candidate", "prompt_asset", "../private:env", "version-1")
        self.client_type.assert_not_called()

    def test_stale_value_is_rejected_without_writing(self):
        with self.assertRaisesRegex(cfg.ConfigurationConflict, "changed"):
            cfg.update_experience_setting("candidate", "tone", "warm", "older-version")
        self.client.set_configuration_setting.assert_not_called()
        self.assertEqual(self.current.value, "neutral")

    def test_concurrent_change_or_deletion_is_not_overwritten(self):
        for error_type in (cfg.ResourceModifiedError, cfg.ResourceNotFoundError):
            with self.subTest(error_type=error_type):
                self.current.value = "neutral"
                self.client.set_configuration_setting.side_effect = error_type()
                with self.assertRaises(cfg.ConfigurationConflict):
                    cfg.update_experience_setting("candidate", "tone", "warm", "version-1")
        self.client.add_configuration_setting.assert_not_called()

    def test_missing_setting_is_not_created(self):
        self.client.get_configuration_setting.side_effect = cfg.ResourceNotFoundError()
        with self.assertRaises(cfg.ConfigurationConflict):
            cfg.load_editable_setting("candidate", "tone")
        with self.assertRaises(cfg.ConfigurationConflict):
            cfg.update_experience_setting("candidate", "tone", "warm", "version-1")
        self.client.set_configuration_setting.assert_not_called()
        self.client.add_configuration_setting.assert_not_called()

    def test_unchanged_value_does_not_write(self):
        self.assertEqual(cfg.update_experience_setting("candidate", "tone", "neutral", "version-1"), {
            "value": "neutral", "etag": "version-1",
        })
        self.client.set_configuration_setting.assert_not_called()

    def test_editor_does_not_enable_generic_writes_publishing_or_audit(self):
        for operation in (
            lambda: cfg.set_value("tone", "warm", store="production", persona="app"),
            lambda: cfg.publish_draft("app"), lambda: cfg.probe("app"),
            lambda: audit.run_query(audit.CHANGES_QUERY),
            lambda: rbac.credential_for("approver"),
        ):
            with self.subTest(operation=operation), self.assertRaises(rbac.OperationDisabled):
                operation()
        self.client_type.assert_not_called()

    def test_real_authorization_failure_is_still_an_azure_denial(self):
        error = cfg.HttpResponseError("synthetic denial")
        error.status_code = 403
        self.client.set_configuration_setting.side_effect = error
        with self.assertRaises(cfg.AccessDenied):
            cfg.update_experience_setting("candidate", "tone", "warm", "version-1")


if __name__ == "__main__":
    unittest.main()