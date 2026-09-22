import os
import unittest
from unittest.mock import Mock, patch

import knowledge
from experience_runtime import ConfiguredResponseRuntime, run_grounded
from search_settings import DEFAULT_QUESTION, DEFAULTS, normalize_settings
import rbac
from experience_runtime import ConfiguredResponseRuntime, run_grounded


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

    @patch.dict(os.environ, {"ELV_HOSTING_MODE": "azure-vm", "ELV_DEMO_MODE": "comparison"})
    @patch("experience_runtime.run_variant")
    def test_comparison_skips_knowledge_and_pins_until_refresh(self, run_variant):
        run_variant.side_effect = lambda profile, message: {"text": profile["tone"]}
        knowledge_loader = Mock(side_effect=AssertionError("knowledge read"))
        runtime = ConfiguredResponseRuntime(
            profile_loader=self.load_profile, knowledge_loader=knowledge_loader
        )
        first = runtime.invoke("context-1", "hello")
        self.current_profile["tone"] = "formal"
        self.assertEqual(runtime.invoke("context-1", "again")["result"]["text"], "warm")
        refreshed = runtime.invoke("context-2", "hello")
        self.assertEqual(refreshed["result"]["text"], "formal")
        self.assertNotEqual(first["configuration_revision"], refreshed["configuration_revision"])
        self.assertEqual(first["found"]["documents"], [])
        knowledge_loader.assert_not_called()

    @patch.dict(os.environ, {"ELV_HOSTING_MODE": "azure-vm", "ELV_DEMO_MODE": "comparison"})
    @patch("experience_runtime.generate_response")
    @patch("experience_runtime.knowledge.search")
    def test_comparison_rejects_grounding_before_configuration_or_model_calls(self, search, generate):
        runtime = self.runtime()
        with self.assertRaises(rbac.OperationDisabled):
            runtime.invoke("context-1", "hello", grounded=True)
        with self.assertRaises(rbac.OperationDisabled):
            run_grounded({}, {"enabled": "true"}, "hello", "app")
        runtime.persona = "approver"
        with self.assertRaises(rbac.OperationDisabled):
            runtime.invoke("context-2", "hello")
        self.assertEqual(self.profile_loads, [])
        search.assert_not_called()
        generate.assert_not_called()

    @patch.dict(os.environ, {"ELV_HOSTING_MODE": "azure-vm", "ELV_DEMO_MODE": "comparison"})
    @patch("experience_runtime.run_variant")
    def test_comparison_empty_profile_is_not_replaced_by_local_defaults(self, run_variant):
        self.current_profile = {}
        with self.assertRaisesRegex(RuntimeError, "baseline profile is empty"):
            self.runtime().invoke("context-1", "hello")
        run_variant.assert_not_called()


if __name__ == "__main__":
    unittest.main()