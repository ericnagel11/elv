import unittest
from unittest.mock import patch

from experience_runtime import ConfiguredResponseRuntime


class ConfiguredResponseRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.current_profile = {
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

        first = runtime.invoke("context-1", "hello", "baseline")
        self.current_profile["tone"] = "formal"
        pinned = runtime.invoke("context-1", "again", "baseline")
        refreshed = runtime.invoke("context-2", "hello", "baseline")

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
        runtime.invoke("context-1", "hello", "baseline")

        with self.assertRaisesRegex(ValueError, "cannot change profile_slot"):
            runtime.invoke("context-1", "hello", "candidate")

    def test_unknown_profile_slot_is_rejected_before_loading_configuration(self):
        runtime = self.runtime()

        with self.assertRaisesRegex(ValueError, "baseline, candidate"):
            runtime.invoke("context-1", "hello", "draft")

        self.assertEqual(self.profile_loads, [])


if __name__ == "__main__":
    unittest.main()