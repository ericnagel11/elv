import os
import unittest
from unittest.mock import Mock, patch

from azure.core.exceptions import HttpResponseError

import knowledge
import rbac
import config as cfg
from experience_runtime import ConfiguredResponseRuntime, run_grounded


EXISTING_INDEX_SETTINGS = {
    "enabled": "true",
    "index": "medical-policies-vector",
    "title_field": "Title",
    "content_field": "Content",
    "status_field": "Status",
    "state_field": "State",
    "source_field": "BlobName",
    "effective_date_field": "PublishDate",
    "url_field": "",
    "industry_field": "",
    "audience_field": "",
    "search_fields": "Title,Content",
    "top_k": "3",
    "query_mode": "simple",
    "citation_style": "inline",
    "filter": "Status eq 'Approved' and State eq 'CA'",
}


class ExistingIndexMappingTests(unittest.TestCase):
    def test_legacy_default_fields_are_preserved(self):
        client = Mock()
        client.search.return_value = []
        knowledge._run(client, "synthetic question", {}, semantic=False)
        self.assertEqual(client.search.call_args.kwargs["select"], knowledge.SELECT_FIELDS)

    @patch.object(knowledge, "_client")
    def test_existing_index_fields_and_filter_are_used_exactly(self, factory):
        factory.return_value.search.return_value = [{
            "Title": "Synthetic policy", "Content": "Approved example content.",
            "Status": "Approved", "State": "CA", "BlobName": "example.pdf",
            "PublishDate": "2026-01-01", "@search.score": 1.5,
        }]
        found = knowledge.search("synthetic question", EXISTING_INDEX_SETTINGS, "app")
        factory.assert_called_once_with("medical-policies-vector", "app")
        arguments = factory.return_value.search.call_args.kwargs
        self.assertEqual(arguments["select"], ["Title", "Content", "Status", "PublishDate", "State", "BlobName"])
        self.assertEqual(arguments["search_fields"], ["Title", "Content"])
        self.assertEqual(arguments["filter"], EXISTING_INDEX_SETTINGS["filter"])
        self.assertEqual(arguments["top"], 3)
        self.assertNotIn("vector_queries", arguments)
        document = found["documents"][0]
        self.assertEqual(document["title"], "Synthetic policy")
        self.assertEqual(document["source"], "example.pdf")
        self.assertEqual(document["state"], "CA")
        self.assertEqual(document["url"], "")
        self.assertIn("state: CA", knowledge.format_context(found["documents"]))
        self.assertEqual(knowledge.citation_list(found["documents"])[0]["source"], "example.pdf")

    def test_blank_optional_mappings_do_not_restore_unavailable_legacy_fields(self):
        settings = knowledge.settings_from_profile(EXISTING_INDEX_SETTINGS)
        self.assertEqual(settings["url_field"], "")
        self.assertEqual(knowledge.field_mapping(settings)["industry"], "")

    def test_blank_vm_filter_survives_healthcare_defaults_and_normalization(self):
        for expression in ("", " \n\t "):
            with self.subTest(expression=expression):
                profile = {**EXISTING_INDEX_SETTINGS, "filter": expression,
                           "enabled": True, "top_k": 3, "query_mode": " SIMPLE "}
                settings = knowledge.settings_from_profile(profile)
                self.assertEqual(settings["filter"], "")
                self.assertEqual(settings["enabled"], "true")
                self.assertEqual(settings["query_mode"], "simple")
                self.assertEqual(settings["content_field"], "Content")
                self.assertEqual(settings["industry_field"], "")
                client = Mock()
                client.search.return_value = []
                knowledge._run(client, "synthetic question", settings, semantic=False)
                self.assertNotIn("filter", client.search.call_args.kwargs)
                self.assertEqual(client.search.call_args.kwargs["search_fields"], ["Title", "Content"])
                self.assertEqual(profile["filter"], expression)

    def test_missing_filter_uses_healthcare_default_without_losing_custom_fields(self):
        profile = {key: value for key, value in EXISTING_INDEX_SETTINGS.items() if key != "filter"}
        profile["semantic_configuration"] = "existing-semantic"
        settings = knowledge.settings_from_profile(profile)
        self.assertEqual(settings["filter"], knowledge.DEFAULTS["filter"])
        self.assertEqual(settings["semantic_configuration"], "existing-semantic")
        self.assertEqual(settings["status_field"], "Status")

    @patch.object(knowledge, "_client")
    def test_invalid_or_missing_content_mapping_fails_before_client_creation(self, factory):
        for field in ("", "Content,*", "Content;other", "../Content"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                knowledge.search("question", {**EXISTING_INDEX_SETTINGS, "content_field": field}, "app")
        factory.assert_not_called()

    @patch.object(knowledge, "_client")
    def test_content_is_bounded_and_empty_chunks_are_not_cited(self, factory):
        factory.return_value.search.return_value = [
            {"Title": "Empty", "Content": "  "},
            {"Title": "Long", "Content": "x" * (knowledge.MAX_CHARS_PER_DOCUMENT + 10)},
        ]
        found = knowledge.search("question", EXISTING_INDEX_SETTINGS, "app")
        self.assertEqual(len(found["documents"]), 1)
        self.assertTrue(found["documents"][0]["truncated"])
        self.assertEqual(len(found["documents"][0]["content"]), knowledge.MAX_CHARS_PER_DOCUMENT)

    @patch.object(knowledge, "_client")
    def test_invalid_keyword_filter_never_retries_without_filter(self, factory):
        error = HttpResponseError("private service details and filter literals must not reach the UI")
        error.status_code = 400
        factory.return_value.search.side_effect = error
        with self.assertRaisesRegex(ValueError, "Azure AI Search rejected the query") as caught:
            knowledge.search("question", EXISTING_INDEX_SETTINGS, "app")
        self.assertIn("case-sensitive", str(caught.exception))
        self.assertIn("Configuration > Knowledge", str(caught.exception))
        self.assertNotIn("private service details", str(caught.exception))
        self.assertEqual(factory.return_value.search.call_count, 1)
        self.assertEqual(factory.return_value.search.call_args.kwargs["filter"], EXISTING_INDEX_SETTINGS["filter"])

    def test_configured_semantic_name_is_not_hardcoded_to_sample_index(self):
        client = Mock()
        client.search.return_value = []
        knowledge._run(client, "question", {
            **EXISTING_INDEX_SETTINGS, "semantic_configuration": "existing-semantic",
        }, semantic=True)
        self.assertEqual(client.search.call_args.kwargs["semantic_configuration_name"], "existing-semantic")
        self.assertEqual(client.search.call_args.kwargs["filter"], EXISTING_INDEX_SETTINGS["filter"])


RAG_ENV = {
    "ELV_HOSTING_MODE": "azure-vm", "ELV_DEMO_MODE": "comparison",
    "ELV_ENABLE_RAG": "true", "ELV_SEARCH_ALLOWED_INDEXES": "medical-policies-vector",
    "AZURE_SEARCH_ENDPOINT": "https://example.search.windows.net",
}


class ComparisonRagPolicyTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, RAG_ENV, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    @patch.object(knowledge, "_client")
    def test_unapproved_index_or_persona_fails_before_query(self, factory):
        for index, persona in (("other-index", "app"), ("medical-policies-vector", "approver")):
            with self.subTest(index=index, persona=persona), self.assertRaises(rbac.OperationDisabled):
                knowledge.search("question", {**EXISTING_INDEX_SETTINGS, "index": index}, persona)
        factory.assert_not_called()

    @patch.object(knowledge, "_client")
    def test_rag_is_disabled_by_default_and_invalid_opt_in_fails_closed(self, factory):
        os.environ.pop("ELV_ENABLE_RAG")
        with self.assertRaises(rbac.OperationDisabled):
            knowledge.search("question", EXISTING_INDEX_SETTINGS, "app")
        os.environ["ELV_ENABLE_RAG"] = "yes"
        with self.assertRaisesRegex(ValueError, "ELV_ENABLE_RAG"):
            knowledge.search("question", EXISTING_INDEX_SETTINGS, "app")
        factory.assert_not_called()

    def test_missing_or_malformed_index_allowlist_is_rejected(self):
        for value in ("", "*", "medical-policies-vector,", "https://other/index"):
            with self.subTest(value=value), patch.dict(os.environ, {"ELV_SEARCH_ALLOWED_INDEXES": value}):
                with self.assertRaisesRegex(ValueError, "ELV_SEARCH_ALLOWED_INDEXES"):
                    rbac.require_grounding("medical-policies-vector", "app")

    @patch.object(cfg, "_client")
    def test_only_approved_profile_knowledge_reads_are_enabled(self, factory):
        factory.return_value.list_configuration_settings.return_value = []
        self.assertEqual(cfg.load_knowledge("baseline", "production", "app"), {})
        factory.return_value.list_configuration_settings.assert_called_once_with(
            key_filter="knowledge:*", label_filter="baseline"
        )
        for label, store, persona in (("candidate", "draft", "app"), ("other", "production", "app"),
                                       ("baseline", "production", "approver")):
            with self.subTest(label=label, store=store), self.assertRaises(rbac.OperationDisabled):
                cfg.load_knowledge(label, store, persona)
        self.assertEqual(factory.call_count, 1)

    @patch("experience_runtime.generate_response")
    @patch("experience_runtime.knowledge.search")
    def test_no_sources_does_not_invoke_model(self, search, generate):
        search.return_value = {"documents": [], "notes": ["No match"], "index": "medical-policies-vector"}
        bundle = run_grounded({"tone": "warm"}, EXISTING_INDEX_SETTINGS, "question", "app")
        self.assertEqual(bundle["result"]["finish_reason"], "no_sources")
        self.assertIn("No matching source text", bundle["result"]["text"])
        self.assertFalse(bundle["grounded"])
        generate.assert_not_called()

    @patch("experience_runtime.generate_response")
    @patch("experience_runtime.knowledge.search")
    def test_inline_mode_withholds_missing_or_invalid_markers_without_retry(self, search, generate):
        search.return_value = {
            "documents": [{"title": "Synthetic policy", "content": "Example reference.",
                           "industry": "", "status": "Reviewed", "effective_date": ""}],
            "notes": [], "index": "medical-policies-vector",
        }
        for text, status in (("Unsupported uncited advice.", "missing"),
                             ("Unsupported source [2].", "invalid"),
                             ("Mixed source numbers [1] and [0].", "invalid")):
            with self.subTest(text=text):
                generate.reset_mock()
                generate.return_value = {"text": text, "finish_reason": "stop", "completion_tokens": 20}
                bundle = run_grounded({"tone": "warm"}, EXISTING_INDEX_SETTINGS, "question", "app")
                self.assertEqual(bundle["citation_status"], status)
                self.assertEqual(bundle["result"]["finish_reason"], "citation_validation_failed")
                self.assertNotIn(text, bundle["result"]["text"])
                self.assertIn("answer was withheld", bundle["result"]["text"])
                self.assertEqual(bundle["result"]["completion_tokens"], 20)
                generate.assert_called_once()

    @patch("experience_runtime.generate_response")
    @patch("experience_runtime.knowledge.search")
    def test_valid_inline_markers_and_none_mode_leave_model_text_unchanged(self, search, generate):
        search.return_value = {
            "documents": [{"title": "Synthetic policy", "content": "Example reference.",
                           "industry": "", "status": "Reviewed", "effective_date": ""}],
            "notes": [], "index": "medical-policies-vector",
        }
        for style, text, status in (("inline", "Example statement [1].", "present"),
                                    ("none", "Example statement.", "not_requested")):
            with self.subTest(style=style):
                generate.return_value = {"text": text, "finish_reason": "stop"}
                bundle = run_grounded({}, {**EXISTING_INDEX_SETTINGS, "citation_style": style}, "question", "app")
                self.assertEqual(bundle["result"]["text"], text)
                self.assertEqual(bundle["citation_status"], status)
                self.assertEqual(generate.call_args.args[1]["citation_style"], style)

    @patch("experience_runtime.generate_response")
    @patch("experience_runtime.knowledge.search")
    def test_direct_vm_preview_never_uses_model_for_disabled_or_missing_search(self, search, generate):
        with self.assertRaisesRegex(ValueError, "knowledge:enabled"):
            run_grounded({}, {**EXISTING_INDEX_SETTINGS, "enabled": "false"}, "question", "app")
        os.environ.pop("AZURE_SEARCH_ENDPOINT")
        with self.assertRaisesRegex(ValueError, "AZURE_SEARCH_ENDPOINT"):
            run_grounded({}, EXISTING_INDEX_SETTINGS, "question", "app")
        search.assert_not_called()
        generate.assert_not_called()

    @patch("experience_runtime.run_grounded")
    def test_knowledge_filter_is_pinned_until_a_new_context(self, grounded):
        profile_loader = Mock(return_value={"tone": "warm", "prompt_asset": "response:v1"})
        scope = dict(EXISTING_INDEX_SETTINGS)
        knowledge_loader = Mock(side_effect=lambda *args: dict(scope))
        grounded.return_value = {"result": {"text": "Synthetic grounded reply"}, "found": {"documents": []}}
        runtime = ConfiguredResponseRuntime(profile_loader=profile_loader, knowledge_loader=knowledge_loader)
        first = runtime.invoke("context-1", "question", grounded=True)
        scope["filter"] = "State eq 'NY'"
        pinned = runtime.invoke("context-1", "question", grounded=True)
        refreshed = runtime.invoke("context-2", "question", grounded=True)
        self.assertEqual(first["configuration_revision"], pinned["configuration_revision"])
        self.assertNotEqual(first["configuration_revision"], refreshed["configuration_revision"])
        self.assertEqual(grounded.call_args_list[1].args[1]["filter"], EXISTING_INDEX_SETTINGS["filter"])
        self.assertEqual(grounded.call_args_list[2].args[1]["filter"], "State eq 'NY'")
        self.assertEqual(knowledge_loader.call_count, 2)

    @patch("experience_runtime.run_variant")
    @patch("experience_runtime.run_grounded")
    def test_disabled_grounded_profile_never_silently_generates_ungrounded_answer(self, grounded, variant):
        runtime = ConfiguredResponseRuntime(
            profile_loader=Mock(return_value={"tone": "warm"}),
            knowledge_loader=Mock(return_value={"enabled": "false"}),
        )
        with self.assertRaisesRegex(ValueError, "knowledge:enabled"):
            runtime.invoke("context-1", "question", grounded=True)
        grounded.assert_not_called()
        variant.assert_not_called()

    @patch.object(knowledge, "_client")
    def test_semantic_and_vector_modes_are_not_claimed_without_configuration(self, factory):
        for mode in ("semantic", "vector", "hybrid"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "query_mode"):
                knowledge.search("question", {**EXISTING_INDEX_SETTINGS, "query_mode": mode}, "app")
        factory.assert_not_called()


class KnowledgeEditorTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {**RAG_ENV, "ELV_ENABLE_CONFIG_EDITING": "true"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.factory = self.enterContext(patch.object(cfg, "_client"))
        self.current = cfg.ConfigurationSetting(
            key="knowledge:filter", label="candidate", value="State eq 'NY'",
            etag="version-1", tags={"owner": "demo"},
        )
        self.factory.return_value.get_configuration_setting.return_value = self.current
        self.factory.return_value.set_configuration_setting.return_value = cfg.ConfigurationSetting(
            key="knowledge:filter", label="candidate", value="State eq 'CA'", etag="version-2",
        )

    def test_filter_read_and_save_use_existing_key_with_version_check(self):
        loaded = cfg.load_editable_setting("candidate", "filter", prefix=cfg.KNOWLEDGE_PREFIX)
        self.assertEqual(loaded["etag"], "version-1")
        result = cfg.update_knowledge_setting("candidate", "filter", "State eq 'CA'", "version-1")
        self.assertEqual(result["etag"], "version-2")
        self.factory.assert_called_with("production", "app")
        self.factory.return_value.get_configuration_setting.assert_called_with(key="knowledge:filter", label="candidate")
        self.factory.return_value.set_configuration_setting.assert_called_once_with(
            self.current, etag="version-1", match_condition=cfg.MatchConditions.IfNotModified,
        )
        self.assertEqual(self.current.tags, {"owner": "demo"})

    def test_blank_filter_and_optional_field_mapping_are_valid_for_approved_whole_index(self):
        for key in ("filter", "url_field", "industry_field", "audience_field"):
            with self.subTest(key=key):
                cfg.validate_knowledge_value(key, "")

    def test_rag_opt_out_blocks_knowledge_reads_and_saves(self):
        os.environ["ELV_ENABLE_RAG"] = "false"
        with self.assertRaises(rbac.OperationDisabled):
            cfg.load_editable_setting("candidate", "filter", prefix=cfg.KNOWLEDGE_PREFIX)
        with self.assertRaises(rbac.OperationDisabled):
            cfg.update_knowledge_setting("candidate", "filter", "", "version-1")
        self.factory.assert_not_called()

    def test_unapproved_index_other_prefix_and_invalid_controls_fail_before_client(self):
        for key, value in (("index", "another-index"), ("top_k", "0"), ("top_k", "21"),
                           ("enabled", "yes"), ("query_mode", "vector"), ("content_field", ""),
                           ("search_fields", "Title,,Content"), ("citation_style", "invented")):
            with self.subTest(key=key, value=value), self.assertRaises((ValueError, rbac.OperationDisabled)):
                cfg.update_knowledge_setting("candidate", key, value, "version-1")
        with self.assertRaises(rbac.OperationDisabled):
            cfg.load_editable_setting("candidate", "filter", prefix="other:")
        self.factory.assert_not_called()

    def test_stale_knowledge_save_does_not_write(self):
        with self.assertRaises(cfg.ConfigurationConflict):
            cfg.update_knowledge_setting("candidate", "filter", "", "old-version")
        self.factory.return_value.set_configuration_setting.assert_not_called()


class LiveKnowledgeFormTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {**RAG_ENV, "ELV_ENABLE_CONFIG_EDITING": "true"}, clear=True))
        self.factory = self.enterContext(patch.object(cfg, "_client"))
        self.client = self.factory.return_value
        self.values = {key: EXISTING_INDEX_SETTINGS[key] for key in cfg.EDITABLE_KNOWLEDGE_KEYS}
        self.etags = {key: f"version-{key}" for key in self.values}
        self.stored = {
            f"knowledge:{key}": cfg.ConfigurationSetting(
                key=f"knowledge:{key}", label="candidate", value=value,
                etag=self.etags[key], tags={"owner": "demo"},
            ) for key, value in self.values.items()
        }
        self.client.get_configuration_setting.side_effect = lambda *, key, label: self.stored[key]
        self.client.set_configuration_setting.side_effect = lambda setting, **kwargs: setting

    def test_load_reads_actual_values_and_versions_without_writes(self):
        self.assertEqual(cfg.load_live_knowledge("candidate"), {"settings": self.values, "etags": self.etags})
        self.assertEqual(self.client.get_configuration_setting.call_count, 6)
        self.client.set_configuration_setting.assert_not_called()
        self.factory.assert_called_with("production", "app")

    def test_grouped_save_updates_only_changed_controls_and_never_field_mappings(self):
        submitted = {**self.values, "filter": "", "top_k": 5}
        result = cfg.update_live_knowledge("candidate", submitted, self.etags)
        self.assertEqual(result.changed_keys, ["knowledge:filter", "knowledge:top_k"])
        self.assertEqual(len(result.unchanged_keys), 4)
        self.assertEqual(result.outcome, "success")
        writes = self.client.set_configuration_setting.call_args_list
        self.assertEqual(len(writes), 2)
        for write in writes:
            setting = write.args[0]
            self.assertEqual(setting.tags, {"owner": "demo"})
            self.assertEqual(write.kwargs["etag"], self.etags[setting.key.split(":", 1)[1]])
            self.assertEqual(write.kwargs["match_condition"], cfg.MatchConditions.IfNotModified)
        self.client.add_configuration_setting.assert_not_called()
        self.client.delete_configuration_setting.assert_not_called()

    def test_invalid_controls_or_versions_fail_before_client_reads(self):
        cases = [
            ({**self.values, "index": "unapproved-index"}, self.etags),
            ({**self.values, "query_mode": "semantic"}, self.etags),
            ({**self.values, "content_field": "OtherContent"}, self.etags),
            ({**self.values, "top_k": 30}, self.etags),
            (self.values, {**self.etags, "filter": "*"}),
            ({key: value for key, value in self.values.items() if key != "filter"}, self.etags),
            (self.values, {}),
        ]
        for values, etags in cases:
            with self.subTest(values=values, etags=etags), self.assertRaises((ValueError, rbac.OperationDisabled)):
                cfg.update_live_knowledge("candidate", values, etags)
        self.factory.assert_not_called()

    def test_stale_control_stops_the_entire_save_before_any_write(self):
        self.stored["knowledge:citation_style"].etag = "new-version"
        with self.assertRaises(cfg.ConfigurationConflict):
            cfg.update_live_knowledge("candidate", {**self.values, "filter": ""}, self.etags)
        self.client.set_configuration_setting.assert_not_called()

    def test_partial_failure_records_confirmed_writes_without_rollback(self):
        def save(setting, **kwargs):
            if setting.key == "knowledge:top_k":
                raise cfg.ResourceModifiedError()
            return setting

        self.client.set_configuration_setting.side_effect = save
        with self.assertRaises(cfg.ConfigurationConflict) as caught:
            cfg.update_live_knowledge("candidate", {**self.values, "filter": "", "top_k": "5"}, self.etags)
        result = caught.exception.mutation_result
        self.assertEqual(result.outcome, "partial")
        self.assertEqual(result.changed_keys, ["knowledge:filter"])
        self.assertEqual(result.failed_key, "knowledge:top_k")
        self.assertEqual(result.not_attempted, ["knowledge:query_mode", "knowledge:citation_style"])
        self.assertEqual(self.client.set_configuration_setting.call_count, 2)
        self.client.delete_configuration_setting.assert_not_called()

    def test_vm_opt_in_still_required_for_grouped_controls(self):
        os.environ["ELV_ENABLE_CONFIG_EDITING"] = "false"
        with self.assertRaises(rbac.OperationDisabled):
            cfg.load_live_knowledge("candidate")
        with self.assertRaises(rbac.OperationDisabled):
            cfg.update_live_knowledge("candidate", self.values, self.etags)
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()