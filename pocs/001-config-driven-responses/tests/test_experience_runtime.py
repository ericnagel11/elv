import unittest
from unittest.mock import Mock, patch

import knowledge
from experience_runtime import ConfiguredResponseRuntime, run_grounded
from search_settings import DEFAULT_QUESTION, DEFAULTS, normalize_settings


class ConfiguredResponseRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.current_profile = {
            "persona": "a Contoso Health Plan member support agent",
            "tone": "warm",
            "prompt_asset": "response:v1",
        }
        self.profile_loads = []

    def load_profile(self, label, store, persona):
        self.profile_loads.append((label, store, persona))
        return dict(self.current_profile)

    @staticmethod
    def load_knowledge(label, store, persona):
        return {"enabled": "false"}

    def runtime(self):
        return ConfiguredResponseRuntime(
            profile_loader=self.load_profile,
            knowledge_loader=self.load_knowledge,
        )

    @patch("experience_runtime.run_variant")
    def test_configuration_is_pinned_until_a_new_context(self, run_variant):
        run_variant.side_effect = lambda profile, message: {
            "text": profile["tone"],
            "messages": [],
            "latency_s": 0,
        }
        runtime = self.runtime()

        first = runtime.invoke("context-1", DEFAULT_QUESTION, "baseline")
        self.current_profile["tone"] = "formal"
        pinned = runtime.invoke("context-1", DEFAULT_QUESTION, "baseline")
        refreshed = runtime.invoke("context-2", DEFAULT_QUESTION, "baseline")

        self.assertEqual(first["result"]["text"], "warm")
        self.assertEqual(pinned["result"]["text"], "warm")
        self.assertEqual(refreshed["result"]["text"], "formal")
        self.assertEqual(
            first["configuration_revision"], pinned["configuration_revision"]
        )
        self.assertNotEqual(
            first["configuration_revision"], refreshed["configuration_revision"]
        )
        self.assertEqual(
            self.profile_loads,
            [
                ("baseline", "production", "app"),
                ("baseline", "production", "app"),
            ],
        )

    @patch("experience_runtime.run_variant")
    def test_existing_context_cannot_switch_profile_slot(self, run_variant):
        run_variant.return_value = {"text": "ok", "messages": [], "latency_s": 0}
        runtime = self.runtime()
        runtime.invoke("context-1", DEFAULT_QUESTION, "baseline")

        with self.assertRaisesRegex(ValueError, "cannot change profile_slot"):
            runtime.invoke("context-1", DEFAULT_QUESTION, "candidate")

    def test_unknown_profile_slot_is_rejected_before_loading_configuration(self):
        runtime = self.runtime()

        with self.assertRaisesRegex(ValueError, "baseline, candidate"):
            runtime.invoke("context-1", DEFAULT_QUESTION, "draft")

        self.assertEqual(self.profile_loads, [])

    def test_request_and_configuration_must_both_enable_grounding(self):
        for requested, enabled in ((False, "true"), (False, "false"), (True, "false")):
            with self.subTest(requested=requested, enabled=enabled), \
                    patch("experience_runtime.run_variant", return_value={"text": "general guidance"}) as variant, \
                    patch("experience_runtime.run_grounded") as grounded, \
                    patch("knowledge.search") as search:
                runtime = ConfiguredResponseRuntime(
                    profile_loader=self.load_profile,
                    knowledge_loader=lambda *args: {"enabled": enabled},
                )
                bundle = runtime.invoke("c", DEFAULT_QUESTION, grounded=requested)
                variant.assert_called_once_with(self.current_profile, DEFAULT_QUESTION)
                grounded.assert_not_called()
                search.assert_not_called()
                self.assertFalse(bundle["grounded"])
                self.assertEqual(bundle["prompt_asset"], "response:v1")
                self.assertEqual(bool(bundle["found"]["notes"]), requested)

    def test_enabled_scope_is_pinned_and_reaches_grounded_runner(self):
        scope = {"enabled": "true", "filter": "", "top_k": "7", "index": "member-index"}
        with patch("experience_runtime.run_grounded", return_value={
            "result": {"text": "reference response"},
            "found": {"documents": [{"title": "Member support"}], "notes": [], "index": "member-index"},
        }) as grounded:
            runtime = ConfiguredResponseRuntime(
                persona="app", profile_loader=self.load_profile,
                knowledge_loader=lambda *args: dict(scope),
            )
            first = runtime.invoke("c", DEFAULT_QUESTION, grounded=True)
            grounded.assert_called_with(self.current_profile, normalize_settings(scope), DEFAULT_QUESTION, "app")
            scope["top_k"] = "2"
            second = runtime.invoke("c", DEFAULT_QUESTION, grounded=True)
            self.assertEqual(grounded.call_args.args[1]["top_k"], "7")
            third = runtime.invoke("new", DEFAULT_QUESTION, grounded=True)
        self.assertEqual(first["configuration_revision"], second["configuration_revision"])
        self.assertNotEqual(first["configuration_revision"], third["configuration_revision"])
        self.assertTrue(first["grounded"])
        self.assertEqual(first["prompt_asset"], "response:v3")


class GroundedPreviewTests(unittest.TestCase):
    def setUp(self):
        self.profile = {"persona": "a Contoso Health Plan member support agent", "prompt_asset": "response:v2"}
        # Any unintended model/client construction fails rather than contacting Azure.
        model_guard = patch("experience_runtime.generate_response", return_value={"text": "mock"})
        self.generate = model_guard.start()
        self.addCleanup(model_guard.stop)
        search_guard = patch("knowledge._client", side_effect=AssertionError("No real Search client"))
        self.client_factory = search_guard.start()
        self.addCleanup(search_guard.stop)

    def test_disabled_preview_skips_search_even_without_endpoint(self):
        for scope in ({}, {"enabled": "false"}, {"enabled": False}):
            with self.subTest(scope=scope), patch("knowledge.search") as search, \
                    patch("knowledge.configured") as configured:
                self.generate.reset_mock()
                bundle = run_grounded(self.profile, scope, DEFAULT_QUESTION, "designer")
                search.assert_not_called()
                configured.assert_not_called()
                self.generate.assert_called_once_with("response:v2", {
                    "persona": self.profile["persona"], "user_message": DEFAULT_QUESTION,
                })
                self.assertEqual(bundle["found"]["documents"], [])
                self.assertIsNone(bundle["found"]["index"])
                self.assertTrue(bundle["found"]["notes"][0].startswith("Search grounding is disabled"))
                self.assertFalse(bundle["grounded"])
        self.client_factory.assert_not_called()

    def test_missing_endpoint_is_unavailable_not_grounded(self):
        with patch("knowledge.configured", return_value=False), patch("knowledge.search") as search:
            bundle = run_grounded(self.profile, {"enabled": "true"}, DEFAULT_QUESTION, "designer")
        search.assert_not_called()
        self.client_factory.assert_not_called()
        self.assertFalse(bundle["grounded"])
        self.assertIsNone(bundle["found"]["index"])
        self.assertIn("unavailable", bundle["found"]["notes"][0])
        self.assertEqual(self.generate.call_args.args[0], "response:v3")
        self.assertEqual(self.generate.call_args.args[1]["context"], "")

    def test_enabled_preview_passes_exact_search_arguments_and_citation_style(self):
        raw = {"title": "Contoso Health Plan: Member Support Standards",
               "content": "Synthetic administrative appeal reference.",
               "industry": "healthcare", "status": "approved", "@search.score": 1}
        client = Mock()
        client.search.return_value = [raw]
        self.client_factory.side_effect = None
        self.client_factory.return_value = client
        for query_mode in ("simple", "semantic"):
            for expression in (DEFAULTS["filter"], ""):
                with self.subTest(mode=query_mode, expression=expression), \
                        patch("knowledge.configured", return_value=True):
                    settings = normalize_settings({"enabled": "true", "index": "member-index",
                        "top_k": 7, "query_mode": query_mode, "filter": expression, "citation_style": "footnote"})
                    original = dict(settings)
                    bundle = run_grounded(self.profile, settings, DEFAULT_QUESTION, "designer")
                    expected = {"search_text": DEFAULT_QUESTION, "top": 7, "select": knowledge.SELECT_FIELDS}
                    if expression:
                        expected["filter"] = expression
                    if query_mode == "semantic":
                        expected.update(query_type="semantic", semantic_configuration_name=knowledge.SEMANTIC_CONFIG)
                    client.search.assert_called_with(**expected)
                    self.client_factory.assert_called_with("member-index", "designer")
                    self.assertEqual(settings, original)
                    self.assertTrue(bundle["grounded"])
                    asset, inputs = self.generate.call_args.args
                    self.assertEqual(asset, "response:v3")
                    self.assertEqual(inputs["citation_style"], "footnote")
                    self.assertIn("[1] Contoso Health Plan", inputs["context"])
                    self.assertEqual(inputs["user_message"], DEFAULT_QUESTION)
                    self.assertNotIn("prompt_asset", inputs)

    def test_empty_search_results_do_not_claim_grounding(self):
        found = {"documents": [], "notes": ["No document matched."], "index": "member-index"}
        with patch("knowledge.configured", return_value=True), patch("knowledge.search", return_value=found):
            bundle = run_grounded(self.profile, {"enabled": "true"}, DEFAULT_QUESTION, "designer")
        self.assertFalse(bundle["grounded"])
        self.assertEqual(bundle["found"], found)
        self.assertEqual(self.generate.call_args.args[1]["context"], "")

    def test_search_remains_low_level_even_if_disabled(self):
        client = Mock()
        client.search.return_value = []
        self.client_factory.side_effect = None
        self.client_factory.return_value = client
        knowledge.search(DEFAULT_QUESTION, normalize_settings({"enabled": "false"}), "app")
        client.search.assert_called_once()

    def test_settings_alias_and_delegate_preserve_explicit_empty_filter(self):
        self.assertIs(knowledge.DEFAULTS, DEFAULTS)
        self.assertEqual(knowledge.settings_from_profile({"filter": ""})["filter"], "")


if __name__ == "__main__":
    unittest.main()