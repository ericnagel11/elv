import asyncio
import os
import unittest
from unittest.mock import Mock, patch

import httpx
from a2a.helpers import new_text_message
from azure.core.exceptions import HttpResponseError

from a2a_agent import EXPERIENCE_PROFILE_EXTENSION, build_agent_card, parse_request_options
from a2a_client import A2AClientError, A2ATaskError, ConfiguredAgentClient
from a2a_server import create_app
from experience_runtime import ConfiguredResponseRuntime
from search_settings import DEFAULT_QUESTION


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def invoke(self, context_id, user_message, profile_slot, grounded):
        self.calls.append((context_id, user_message, profile_slot, grounded))
        return {
            "result": {
                "text": f"{profile_slot}: {user_message}" + (" [1]" if grounded else ""),
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
                        "title": "Contoso Health Plan: Member Support Standards",
                        "status": "approved",
                        "score": 0.9,
                        "reranker_score": None,
                    }
                ]
            },
            "profile_slot": profile_slot,
            "configuration_revision": "revision-123",
            "prompt_asset": "response:v3" if grounded else "response:v2",
            "grounded": grounded,
            "citation_style": "inline" if grounded else "none",
            "citation_status": "present" if grounded else "not_requested",
        }


class A2AContractTests(unittest.TestCase):
    def test_agent_card_uses_the_shared_healthcare_question(self):
        card = build_agent_card("http://testserver")
        self.assertEqual(card.skills[0].examples[0], DEFAULT_QUESTION)

    def test_profile_fields_require_the_declared_extension(self):
        message = new_text_message(DEFAULT_QUESTION)
        message.metadata.update({"profileSlot": "candidate"})

        with self.assertRaisesRegex(ValueError, "requires the declared"):
            parse_request_options(message)

    def test_raw_configuration_is_rejected(self):
        message = new_text_message(DEFAULT_QUESTION)
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
                DEFAULT_QUESTION,
                profile_slot="candidate",
                grounded=True,
            )
        )

        self.assertEqual(response["result"]["text"], f"candidate: {DEFAULT_QUESTION} [1]")
        self.assertEqual(response["profile_slot"], "candidate")
        self.assertTrue(response["grounded"])
        self.assertEqual(response["citation_style"], "inline")
        self.assertEqual(response["citation_status"], "present")
        self.assertEqual(response["configuration_revision"], "revision-123")
        self.assertEqual(response["citations"][0]["title"], "Contoso Health Plan: Member Support Standards")
        self.assertEqual(response["result"]["messages"], [])
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(runtime.calls[0][1:], (DEFAULT_QUESTION, "candidate", True))

    def test_rejected_search_filter_reaches_client_without_model_call_or_raw_details(self):
        settings = {"enabled": "true", "index": "medical-policies-vector", "filter": "status ne 'Revised'"}
        runtime = ConfiguredResponseRuntime(
            profile_loader=Mock(return_value={"tone": "warm", "prompt_asset": "response:v1"}),
            knowledge_loader=Mock(return_value=settings),
        )
        app = create_app(runtime=runtime, base_url="http://testserver")
        client = ConfiguredAgentClient(base_url="http://testserver", transport=httpx.ASGITransport(app=app))
        error = HttpResponseError("private response details")
        error.status_code = 400
        environment = {
            "ELV_HOSTING_MODE": "azure-vm", "ELV_DEMO_MODE": "comparison", "ELV_ENABLE_RAG": "true",
            "ELV_SEARCH_ALLOWED_INDEXES": "medical-policies-vector",
            "AZURE_SEARCH_ENDPOINT": "https://example.search.windows.net",
        }
        with patch.dict(os.environ, environment, clear=True), \
                patch("knowledge._client") as search_client, \
                patch("experience_runtime.generate_response") as generate:
            search_client.return_value.search.side_effect = error
            with self.assertRaisesRegex(A2ATaskError, "Azure AI Search rejected the query") as caught:
                asyncio.run(client.invoke_async(DEFAULT_QUESTION, "candidate", grounded=True))
            self.assertIn("HTTP 400", str(caught.exception))
            self.assertNotIn("private response details", str(caught.exception))
            self.assertNotIn("The configured response failed", str(caught.exception))
            self.assertEqual(search_client.return_value.search.call_count, 1)
            self.assertEqual(search_client.return_value.search.call_args.kwargs["filter"], settings["filter"])
            generate.assert_not_called()

    def test_uncited_answer_is_withheld_with_applied_citation_provenance(self):
        runtime = ConfiguredResponseRuntime(
            profile_loader=Mock(return_value={"tone": "warm", "prompt_asset": "response:v2"}),
            knowledge_loader=Mock(return_value={
                "enabled": "true", "index": "medical-policies-vector", "filter": "", "citation_style": "inline",
            }),
        )
        app = create_app(runtime=runtime, base_url="http://testserver")
        client = ConfiguredAgentClient(base_url="http://testserver", transport=httpx.ASGITransport(app=app))
        environment = {
            "ELV_HOSTING_MODE": "azure-vm", "ELV_DEMO_MODE": "comparison", "ELV_ENABLE_RAG": "true",
            "ELV_SEARCH_ALLOWED_INDEXES": "medical-policies-vector",
            "AZURE_SEARCH_ENDPOINT": "https://example.search.windows.net",
        }
        document = {"title": "Synthetic reference", "content": "Example reference.",
                    "industry": "", "status": "Reviewed", "effective_date": ""}
        with patch.dict(os.environ, environment, clear=True), \
                patch("knowledge.search", return_value={"documents": [document], "notes": [], "index": "medical-policies-vector"}), \
                patch("experience_runtime.generate_response", return_value={
                    "text": "UNCITED_MODEL_DRAFT", "finish_reason": "stop", "completion_tokens": 8,
                }) as generate:
            response = asyncio.run(client.invoke_async(DEFAULT_QUESTION, "candidate", grounded=True))
            self.assertEqual(response["citation_style"], "inline")
            self.assertEqual(response["citation_status"], "missing")
            self.assertEqual(response["result"]["finish_reason"], "citation_validation_failed")
            self.assertNotIn("UNCITED_MODEL_DRAFT", response["result"]["text"])
            self.assertEqual(len(response["citations"]), 1)
            generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()