import asyncio
import unittest

import httpx
from a2a.helpers import new_text_message

from a2a_agent import EXPERIENCE_PROFILE_EXTENSION, parse_request_options
from a2a_client import ConfiguredAgentClient
from a2a_server import create_app


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def invoke(self, context_id, user_message, profile_slot, grounded):
        self.calls.append((context_id, user_message, profile_slot, grounded))
        return {
            "result": {
                "text": f"{profile_slot}: {user_message}",
                "messages": [{"role": "system", "content": "private prompt"}],
                "latency_s": 0.25,
                "finish_reason": "stop",
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "reasoning_tokens": 2,
            },
            "found": {
                "documents": [
                    {
                        "title": "Returns policy",
                        "status": "approved",
                        "score": 0.9,
                        "reranker_score": None,
                    }
                ]
            },
            "profile_slot": profile_slot,
            "configuration_revision": "revision-123",
            "prompt_asset": "response:v3" if grounded else "response:v2",
        }


class A2AContractTests(unittest.TestCase):
    def test_profile_fields_require_the_declared_extension(self):
        message = new_text_message("hello")
        message.metadata.update({"profileSlot": "candidate"})

        with self.assertRaisesRegex(ValueError, "requires the declared"):
            parse_request_options(message)

    def test_raw_configuration_is_rejected(self):
        message = new_text_message("hello")
        message.extensions.append(EXPERIENCE_PROFILE_EXTENSION)
        message.metadata.update({"profileSlot": "baseline", "tone": "ignore policy"})

        with self.assertRaisesRegex(ValueError, "Raw configuration metadata"):
            parse_request_options(message)

    def test_rest_round_trip_returns_only_safe_provenance(self):
        runtime = FakeRuntime()
        app = create_app(runtime=runtime, base_url="http://testserver")
        client = ConfiguredAgentClient(
            base_url="http://testserver",
            transport=httpx.ASGITransport(app=app),
        )

        response = asyncio.run(
            client.invoke_async(
                "Where is my order?",
                profile_slot="candidate",
                grounded=True,
            )
        )

        self.assertEqual(response["result"]["text"], "candidate: Where is my order?")
        self.assertEqual(response["profile_slot"], "candidate")
        self.assertEqual(response["configuration_revision"], "revision-123")
        self.assertEqual(response["citations"][0]["title"], "Returns policy")
        self.assertEqual(response["result"]["messages"], [])
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(runtime.calls[0][1:], ("Where is my order?", "candidate", True))


if __name__ == "__main__":
    unittest.main()