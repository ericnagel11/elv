import asyncio
import os
import unittest
from unittest.mock import Mock, patch

import httpx
import evaluation
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
        self.assertNotIn("evaluation_evidence", response)

    def test_evidence_requires_opt_in_before_generation(self):
        runtime = FakeRuntime()
        client = ConfiguredAgentClient(base_url="http://testserver", transport=httpx.ASGITransport(
            app=create_app(runtime=runtime, base_url="http://testserver"),
        ))
        with patch.dict(os.environ, {"ELV_ENABLE_EVALUATION": "false"}), \
                self.assertRaisesRegex(A2ATaskError, "runtime opt-in"):
            asyncio.run(client.invoke_async(DEFAULT_QUESTION, "baseline", evaluation_evidence=True))
        self.assertEqual(runtime.calls, [])

    def test_opted_in_evidence_keeps_exact_excerpt_and_no_private_fields(self):
        class EvidenceRuntime(FakeRuntime):
            def invoke(self, *args):
                bundle = super().invoke(*args)
                bundle["knowledge_revision"] = "scope-version"
                bundle["found"]["documents"][0].update(
                    content="$50 after deductible", truncated=True, private_filter="secret-filter",
                    url="https://private.invalid", source="private-original",
                )
                return bundle

        environment = {"ELV_HOSTING_MODE": "azure-vm", "ELV_DEMO_MODE": "comparison", "ELV_ENABLE_EVALUATION": "true"}
        with patch.dict(os.environ, environment, clear=True):
            runtime = EvidenceRuntime()
            client = ConfiguredAgentClient(base_url="http://testserver", transport=httpx.ASGITransport(
                app=create_app(runtime=runtime, base_url="http://testserver"),
            ))
            response = asyncio.run(client.invoke_async(DEFAULT_QUESTION, "candidate", grounded=True, evaluation_evidence=True))
        snapshot = response["evaluation_evidence"]
        self.assertEqual(snapshot["sources"][0]["content"], "$50 after deductible")
        self.assertTrue(snapshot["sources"][0]["truncated"])
        self.assertEqual(snapshot["task_id"], response["task_id"])
        self.assertEqual(snapshot["response_hash"], evaluation.text_hash(response["result"]["text"]))
        for private in ("private prompt", "secret-filter", "private.invalid", "private-original"):
            self.assertNotIn(private, evaluation.canonical_json(snapshot))
        self.assertEqual(len(runtime.calls), 1)

    def test_invalid_excerpt_is_unavailable_without_losing_answer(self):
        environment = {"ELV_HOSTING_MODE": "azure-vm", "ELV_DEMO_MODE": "comparison", "ELV_ENABLE_EVALUATION": "true"}
        with patch.dict(os.environ, environment, clear=True):
            client = ConfiguredAgentClient(base_url="http://testserver", transport=httpx.ASGITransport(
                app=create_app(runtime=FakeRuntime(), base_url="http://testserver"),
            ))
            response = asyncio.run(client.invoke_async(DEFAULT_QUESTION, "baseline", grounded=True, evaluation_evidence=True))
        self.assertTrue(response["result"]["text"])
        self.assertEqual(response["evaluation_evidence"]["evidence_status"], "unavailable")
        self.assertEqual(response["evaluation_evidence"]["sources"], [])

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

    def test_unsupported_and_uncited_outcomes_keep_applied_citation_provenance(self):
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
                patch("experience_runtime.generate_response") as generate:
            for draft, status, finish in (
                ("UNCITED_MODEL_DRAFT", "missing", "citation_validation_failed"),
                ("NO_SUPPORTED_ANSWER", "insufficient_evidence", "insufficient_evidence"),
            ):
                with self.subTest(status=status):
                    generate.reset_mock()
                    generate.return_value = {"text": draft, "finish_reason": "stop", "completion_tokens": 8}
                    response = asyncio.run(client.invoke_async(DEFAULT_QUESTION, "candidate", grounded=True))
                    self.assertEqual(response["citation_style"], "inline")
                    self.assertEqual(response["citation_status"], status)
                    self.assertEqual(response["result"]["finish_reason"], finish)
                    self.assertNotIn(draft, response["result"]["text"])
                    self.assertEqual(response["result"]["messages"], [])
                    self.assertEqual(len(response["citations"]), 1)
                    generate.assert_called_once()


class EvaluationA2AContractTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {
            "ELV_HOSTING_MODE": "azure-vm", "ELV_DEMO_MODE": "comparison", "ELV_ENABLE_EVALUATION": "true",
        }, clear=True))

    def test_evaluator_round_trip_and_fresh_profile_policies(self):
        from evaluation_client import EvaluationClient
        from evaluation_server import create_app as create_evaluator
        from test_evaluation import comparison_request, policy_with, setting

        loader = Mock(side_effect=lambda slot: setting(policy_with() if slot == "baseline" else None))
        judge = Mock(side_effect=AssertionError("No model call for literal rules"))
        runtime = evaluation.EvaluationRuntime(loader, judge)
        client = EvaluationClient(base_url="http://testserver", transport=httpx.ASGITransport(
            app=create_evaluator(runtime, "http://testserver"),
        ))
        request = comparison_request()
        report = client.evaluate(request)
        self.assertEqual(report["profiles"]["baseline"]["checks"][0]["outcome"], "finding")
        self.assertEqual(report["profiles"]["candidate"]["state"], "not_configured")
        client.evaluate(request)
        self.assertEqual(loader.call_count, 4)
        judge.assert_not_called()

    def test_evaluator_disabled_and_override_requests_fail_without_execution(self):
        from google.protobuf.json_format import ParseDict
        from google.protobuf.struct_pb2 import Value
        from a2a.types import Part
        from evaluation_agent import parse_request
        from test_evaluation import comparison_request

        message = new_text_message("")
        message.parts.clear()
        message.parts.append(Part(data=ParseDict(comparison_request(), Value()), media_type=evaluation.REQUEST_MEDIA_TYPE))
        self.assertEqual(parse_request(message)["comparison_id"], "comparison-1")
        message.metadata.update({"rules": "bypass"})
        with self.assertRaises(ValueError):
            parse_request(message)
        message.metadata.Clear()
        os.environ["ELV_ENABLE_EVALUATION"] = "false"
        with self.assertRaises(ValueError):
            parse_request(message)

    def test_client_rejects_misattributed_report_and_server_bounds_http(self):
        from evaluation_client import EvaluationClient, EvaluationClientError
        from evaluation_server import MAX_HTTP_BYTES, create_app as create_evaluator
        from test_evaluation import comparison_request, policy_with, setting

        request = comparison_request()
        report = evaluation.EvaluationRuntime(lambda slot: setting(policy_with()), Mock()).evaluate(request)
        report["profiles"]["baseline"]["response_hash"] = "wrong"
        runtime = Mock()
        runtime.evaluate.return_value = report
        application = create_evaluator(runtime, "http://testserver")
        client = EvaluationClient(base_url="http://testserver", transport=httpx.ASGITransport(app=application))
        with self.assertRaises(EvaluationClientError):
            client.evaluate(request)

        async def oversized():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as http_client:
                return await http_client.post("/message:send", content=b"x" * (MAX_HTTP_BYTES + 1))

        runtime.reset_mock()
        self.assertEqual(asyncio.run(oversized()).status_code, 413)
        runtime.evaluate.assert_not_called()


if __name__ == "__main__":
    unittest.main()