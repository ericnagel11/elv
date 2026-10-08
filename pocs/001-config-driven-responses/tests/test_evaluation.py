"""Offline policy and evaluation checks; no credentials or service calls."""

from copy import deepcopy
import json
import unittest
from unittest.mock import Mock

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError

import evaluation


def policy_with(rule_type="literal_phrase"):
    rule = deepcopy(evaluation.RULE_TEMPLATES[rule_type])
    rule["id"] = "demo-rule"
    return {"schema_version": 1, "enabled": True, "rules": [rule]}


def comparison_request(text="You are 100% covered at no cost.", *, sources=True):
    question = "What will my synthetic visit cost?"
    responses = {}
    for slot in evaluation.PROFILE_SLOTS:
        responses[slot] = evaluation.build_snapshot({
            "profile_slot": slot, "configuration_revision": "generation-v1", "knowledge_revision": "scope-v1",
            "prompt_asset": "response:v3", "grounded": sources, "citation_status": "present",
            "result": {"text": text, "finish_reason": "stop"},
            "found": {"documents": [{"title": "Synthetic plan", "content": "$50 after deductible. Excludes out-of-network care.",
                                      "truncated": False, "status": "Reviewed"}] if sources else []},
        }, f"task-{slot}", f"context-{slot}", question)
    return {"schema_version": 1, "comparison_id": "comparison-1", "question": question, "responses": responses}


def setting(policy, etag="policy-v1"):
    return {"policy": policy, "etag": etag}


def judge_check(slot="baseline", **overrides):
    return {"profile_slot": slot, "rule_id": "demo-rule", "outcome": "finding",
            "reason": "Unconditional assurance lacks applicable support.", "response_refs": [f"{slot}:response:passage:1"],
            "evidence_refs": [], "baseline_refs": [], **overrides}


def judge_response(*checks):
    return {"text": json.dumps({"checks": list(checks)}), "finish_reason": "stop",
            "prompt_tokens": 100, "completion_tokens": 30, "model": "offline-judge"}


class PolicyTests(unittest.TestCase):
    def test_templates_round_trip_and_stable_revision(self):
        for rule_type in evaluation.RULE_TEMPLATES:
            with self.subTest(rule_type=rule_type):
                policy = policy_with(rule_type)
                encoded = evaluation.policy_json(policy)
                self.assertEqual(evaluation.parse_policy(encoded), policy)
                self.assertEqual(evaluation.policy_revision(policy), evaluation.policy_revision(json.loads(encoded)))

    def test_rejects_duplicate_unknown_and_invalid_fields(self):
        invalid = [
            '{"schema_version":1,"schema_version":1,"enabled":true,"rules":[]}',
            '{"schema_version":true,"enabled":true,"rules":[]}',
            '{"schema_version":1,"enabled":"true","rules":[]}',
            '{"schema_version":1,"enabled":true,"rules":[],"store":"other"}',
            '{"schema_version":1,"enabled":true,"rules":[],"extra":NaN}',
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                evaluation.parse_policy(value)
        policy = policy_with()
        policy["rules"].append(deepcopy(policy["rules"][0]))
        with self.assertRaises(ValueError):
            evaluation.validate_policy(policy)

    def test_bounded_text_rules_and_bytes(self):
        for field, value in (("id", "../other"), ("criteria", "x" * 801), ("title", "\ud800")):
            policy = policy_with()
            policy["rules"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluation.policy_json(policy)
        policy = policy_with()
        policy["rules"] *= 11
        with self.assertRaises(ValueError):
            evaluation.validate_policy(policy)
        with self.assertRaises(ValueError):
            evaluation.parse_policy(" " * 8193)
        policy = policy_with("absolute_claim")
        policy["rules"] = [{**policy["rules"][0], "id": f"rule-{number}", "criteria": "\u4e2d" * 700} for number in range(4)]
        with self.assertRaises(ValueError):
            evaluation.policy_json(policy)

    def test_literal_matching_is_not_regex_and_keeps_exact_span(self):
        rule = policy_with()["rules"][0]
        rule["parameters"]["terms"] = ["no cost", "100%", ".*"]
        text = "At NO COST, 100% covered; costs are not .* guesses."
        matches = evaluation.literal_matches(text, rule)
        self.assertEqual([match["quote"] for match in matches], ["NO COST", "100%", ".*"])
        for match in matches:
            self.assertEqual(text[match["start"]:match["end"]], match["quote"])
        self.assertEqual(evaluation.literal_matches("Freestyle coverage", {
            **rule, "parameters": {"terms": ["free"], "match": "phrase", "case_sensitive": False},
        }), [])

    def test_literal_rules_are_deliberately_literal(self):
        rule = policy_with()["rules"][0]
        rule["parameters"]["terms"] = ["guaranteed"]
        self.assertTrue(evaluation.literal_matches("Coverage is not guaranteed.", rule))
        self.assertEqual(evaluation.validate_policy({"schema_version": 1, "enabled": True, "rules": []})["rules"], [])


class EvaluationRuntimeTests(unittest.TestCase):
    def run_evaluation(self, policy, request=None, judged=None, candidate=None):
        self.loader = Mock(side_effect=lambda slot: setting(policy if slot == "baseline" else candidate))
        self.judge = Mock(return_value=judged)
        return evaluation.EvaluationRuntime(self.loader, self.judge).evaluate(request or comparison_request())

    def test_missing_disabled_and_empty_are_not_passes(self):
        for policy, state in ((None, "not_configured"), ({"schema_version": 1, "enabled": False, "rules": []}, "disabled"),
                              ({"schema_version": 1, "enabled": True, "rules": []}, "no_active_rules")):
            with self.subTest(state=state):
                report = self.run_evaluation(policy)
                self.assertEqual(report["profiles"]["baseline"]["state"], state)
                self.judge.assert_not_called()

    def test_literal_only_never_calls_model_or_changes_response(self):
        request = comparison_request()
        original = deepcopy(request)
        report = self.run_evaluation(policy_with(), request)
        self.assertEqual(request, original)
        self.assertEqual(report["profiles"]["baseline"]["checks"][0]["outcome"], "finding")
        self.assertEqual(report["profiles"]["candidate"]["state"], "not_configured")
        self.judge.assert_not_called()

    def test_one_semantic_call_has_profile_scoped_rules_and_fixed_options(self):
        report = self.run_evaluation(policy_with("absolute_claim"), judged=judge_response(judge_check()))
        self.assertEqual(report["profiles"]["baseline"]["checks"][0]["severity"], "high")
        self.judge.assert_called_once()
        pending = [("baseline", policy_with("absolute_claim")["rules"][0])]
        _, references = evaluation._judge_context(comparison_request(), pending)
        self.assertEqual(self.judge.call_args.kwargs, {
            "timeout_s": 35.0, "max_retries": 0,
            "response_format": evaluation.judge_response_format(pending, references),
        })
        supplied = json.loads(self.judge.call_args.args[1]["evaluation_input"])
        self.assertEqual([check["profile_slot"] for check in supplied["checks"]], ["baseline"])
        self.assertEqual(report["usage"]["calls"], 1)

    def test_semantic_schema_requires_exact_fields_and_only_pending_rule_ids(self):
        policy = policy_with()
        semantic = deepcopy(evaluation.RULE_TEMPLATES["unsupported_assurance"])
        policy["rules"].append(semantic)
        self.run_evaluation(None, candidate=policy, judged=judge_response(judge_check("candidate", rule_id=semantic["id"])))
        response_format = self.judge.call_args.kwargs["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])
        schema = response_format["json_schema"]["schema"]
        check_schema = schema["properties"]["checks"]["items"]
        self.assertEqual(check_schema["properties"]["profile_slot"]["enum"], ["candidate"])
        self.assertEqual(check_schema["properties"]["rule_id"]["enum"], [semantic["id"]])
        self.assertEqual(set(check_schema["required"]), set(judge_check()))
        self.assertEqual(check_schema["properties"]["outcome"]["enum"], list(evaluation.OUTCOMES))
        self.assertEqual(check_schema["properties"]["response_refs"]["items"]["enum"], ["candidate:response:passage:1"])
        self.assertEqual(check_schema["properties"]["evidence_refs"]["items"]["enum"], ["candidate:1:passage:1"])
        self.assertEqual(check_schema["properties"]["baseline_refs"], {"type": "null"})

        def assert_supported(node):
            if isinstance(node, dict):
                self.assertFalse(set(node).intersection({"minItems", "maxItems", "uniqueItems", "maxLength", "minLength", "pattern"}))
                if node.get("type") == "object":
                    self.assertFalse(node["additionalProperties"])
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                for child in node.values():
                    assert_supported(child)
            elif isinstance(node, list):
                for child in node:
                    assert_supported(child)

        assert_supported(schema)

    def test_wrong_fields_and_unrequested_profile_remain_errors_not_accepted_findings(self):
        wrong_fields = {**judge_check("candidate"), "unexpected": "ignore the contract"}
        for judged in (judge_response(wrong_fields), judge_response(judge_check("baseline"))):
            with self.subTest(judged=judged):
                report = self.run_evaluation(None, candidate=policy_with("unsupported_assurance"), judged=judged)
                self.assertEqual(report["profiles"]["candidate"]["checks"][0]["outcome"], "error")
                self.assertEqual(report["profiles"]["baseline"]["state"], "not_configured")

    def test_safe_negation_and_conditional_text_can_be_not_applicable(self):
        for text in ("Coverage is not guaranteed.", "Prior authorization may be required; your provider can confirm."):
            report = self.run_evaluation(policy_with("unsupported_assurance"), comparison_request(text),
                judge_response(judge_check(outcome="not_applicable", reason="No categorical assurance.", response_refs=[])))
            self.assertEqual(report["profiles"]["baseline"]["checks"][0]["outcome"], "not_applicable")

    def test_prior_authorization_negative_is_reported_without_inventing_determination(self):
        text = "No prior authorization is needed for your MRI."
        report = self.run_evaluation(policy_with("unsupported_assurance"), comparison_request(text, sources=False),
            judge_response(judge_check(evidence_refs=None, baseline_refs=None)))
        self.assertEqual(report["profiles"]["baseline"]["checks"][0]["outcome"], "finding")
        report = self.run_evaluation(policy_with("unsupported_assurance"), comparison_request(text),
            judge_response(judge_check(outcome="no_finding", response_refs=[])))
        self.assertEqual(report["profiles"]["baseline"]["checks"][0]["outcome"], "not_verifiable")

    def test_preservation_requires_source_support_not_baseline_alone(self):
        policy = policy_with("fact_preservation")
        check = judge_check(evidence_refs=["baseline:1:passage:1"])
        report = self.run_evaluation(policy, comparison_request("Your cost is $50."), judge_response(check))
        self.assertEqual(report["profiles"]["baseline"]["checks"][0]["outcome"], "finding")
        check["evidence_refs"] = []
        report = self.run_evaluation(policy, comparison_request("Your cost is $50."), judge_response(check))
        self.assertEqual(report["profiles"]["baseline"]["state"], "unavailable")

    def test_different_scopes_or_no_evidence_are_not_verifiable(self):
        policy = policy_with("fact_preservation")
        request = comparison_request()
        request["responses"]["candidate"]["knowledge_revision"] = "different-scope"
        report = self.run_evaluation(None, request, candidate=policy)
        self.assertEqual(report["profiles"]["candidate"]["checks"][0]["outcome"], "not_verifiable")
        self.judge.assert_not_called()
        report = self.run_evaluation(policy, comparison_request(sources=False))
        self.assertEqual(report["profiles"]["baseline"]["state"], "partial")
        self.judge.assert_not_called()

    def test_truncated_sources_cannot_produce_clean_factual_result(self):
        request = comparison_request("Your cost is $50 after deductible.")
        request["responses"]["baseline"]["sources"][0]["truncated"] = True
        check = judge_check(outcome="no_finding", response_refs=[], evidence_refs=["baseline:1:passage:1"])
        report = self.run_evaluation(policy_with("fact_preservation"), request, judge_response(check))
        self.assertEqual(report["profiles"]["baseline"]["state"], "partial")

    def test_malformed_missing_duplicate_or_invented_judgments_preserve_literal_findings(self):
        policy = policy_with()
        semantic = deepcopy(evaluation.RULE_TEMPLATES["absolute_claim"])
        semantic["id"] = "semantic"
        policy["rules"].append(semantic)
        invalid = [
            {"text": "not JSON", "finish_reason": "stop"},
            judge_response(),
            judge_response(judge_check(rule_id="semantic", response_refs=["Invented quote"])),
            judge_response(judge_check(rule_id="semantic", evidence_refs=["candidate:1:passage:1"])),
            judge_response(judge_check(rule_id="semantic"), judge_check(rule_id="semantic")),
            {**judge_response(judge_check(rule_id="semantic")), "finish_reason": "length"},
        ]
        for judged in invalid:
            with self.subTest(judged=judged):
                report = self.run_evaluation(policy, judged=judged)
                checks = report["profiles"]["baseline"]["checks"]
                self.assertEqual([check["outcome"] for check in checks], ["finding", "error"])
                self.assertEqual(report["profiles"]["baseline"]["state"], "partial")

    def test_fresh_policies_are_loaded_each_call_and_one_failure_is_isolated(self):
        loader = Mock(side_effect=[setting(None), setting(None), setting(policy_with(), "v2"), RuntimeError("private error")])
        judge = Mock()
        runtime = evaluation.EvaluationRuntime(loader, judge)
        self.assertEqual(runtime.evaluate(comparison_request())["profiles"]["baseline"]["state"], "not_configured")
        report = runtime.evaluate(comparison_request())
        self.assertEqual(report["profiles"]["baseline"]["policy_etag"], "v2")
        self.assertEqual(report["profiles"]["candidate"]["state"], "unavailable")
        self.assertNotIn("private error", json.dumps(report))
        self.assertEqual(loader.call_count, 4)
        judge.assert_not_called()

    def test_semantic_failure_reasons_identify_stage_without_exposing_model_text(self):
        secret = "PRIVATE_MODEL_TEXT_DO_NOT_LOG"
        cases = (
            ({"text": secret, "finish_reason": "length"}, "model_finish"),
            ({"text": secret, "finish_reason": "stop"}, "output_json"),
            (judge_response(), "output_schema"),
            (judge_response(judge_check(rule_id="wrong-rule", reason=secret)), "rule_mapping"),
            (judge_response(judge_check(response_refs=[secret])), "rule_evidence"),
        )
        for judged, stage in cases:
            with self.subTest(stage=stage), self.assertLogs("evaluation", level="WARNING") as captured:
                report = self.run_evaluation(policy_with("unsupported_assurance"), judged=judged)
            reason = report["profiles"]["baseline"]["checks"][0]["reason"]
            self.assertIn(f"[{stage}]", reason)
            self.assertIn("No conclusion was accepted", reason)
            self.assertIn(f"stage={stage}", " ".join(captured.output))
            self.assertNotIn(secret, reason + " ".join(captured.output))

    def test_model_failure_categories_do_not_leak_provider_details_or_retry(self):
        request = httpx.Request("POST", "https://private.invalid")
        private = "PRIVATE_PROVIDER_DETAILS_DO_NOT_LOG"
        failures = [
            (APITimeoutError(request=request), "model_timeout"),
            (APIConnectionError(message=private, request=request), "model_connection"),
            (RuntimeError(private), "model_request"),
        ]
        for status, stage in (
            (400, "model_request_rejected"), (401, "model_authentication"),
            (403, "model_authorization"), (404, "model_not_found"), (408, "model_timeout"),
            (413, "model_request_rejected"), (429, "model_rate_limit"), (503, "model_service"),
        ):
            failures.append((APIStatusError(private, response=httpx.Response(status, request=request), body={"error": private}), stage))
        for problem, stage in failures:
            with self.subTest(stage=stage), self.assertLogs("evaluation", level="WARNING") as captured:
                judge = Mock(side_effect=problem)
                runtime = evaluation.EvaluationRuntime(lambda slot: setting(policy_with("unsupported_assurance")), judge)
                report = runtime.evaluate(comparison_request())
            reason = report["profiles"]["candidate"]["checks"][0]["reason"]
            self.assertIn(f"[{stage}]", reason)
            self.assertEqual(report["profiles"]["candidate"]["state"], "unavailable")
            self.assertEqual(report["usage"]["calls"], 1)
            self.assertIsNone(report["usage"]["completion_tokens"])
            self.assertEqual(report["model"], "not_reported")
            judge.assert_called_once()
            self.assertNotIn(private, json.dumps(report) + " ".join(captured.output))
            self.assertNotIn("private.invalid", json.dumps(report) + " ".join(captured.output))

    def test_rate_limit_cooldown_is_bounded_numeric_and_never_retried(self):
        request = httpx.Request("POST", "https://private.invalid")
        for headers, expected in (
            ({"retry-after": "60"}, "Retry after at least 60 seconds."),
            ({"retry-after-ms": "1501"}, "Retry after at least 2 seconds."),
            ({"retry-after": "PRIVATE_HEADER"}, ""),
            ({"retry-after": "9999999999"}, ""),
            ({"retry-after": "0"}, ""),
        ):
            with self.subTest(headers=headers), self.assertLogs("evaluation", level="WARNING") as captured:
                problem = APIStatusError("PRIVATE_PROVIDER_BODY", response=httpx.Response(429, request=request, headers=headers), body=None)
                judge = Mock(side_effect=problem)
                policy = policy_with("unsupported_assurance")
                policy["rules"].append(dict(evaluation.RULE_TEMPLATES["literal_phrase"]))
                runtime = evaluation.EvaluationRuntime(lambda slot: setting(policy), judge)
                report = runtime.evaluate(comparison_request())
            checks = report["profiles"]["candidate"]["checks"]
            self.assertIn("[model_rate_limit]", checks[0]["reason"])
            if expected:
                self.assertIn(expected, checks[0]["reason"])
            else:
                self.assertNotIn("Retry after at least", checks[0]["reason"])
            self.assertEqual(checks[1]["outcome"], "finding")
            self.assertEqual(report["profiles"]["candidate"]["state"], "partial")
            self.assertNotIn("PRIVATE_", json.dumps(report) + " ".join(captured.output))
            judge.assert_called_once()

    def test_timeout_abstention_and_snapshot_tampering(self):
        judge = Mock(side_effect=TimeoutError("secret transport details"))
        runtime = evaluation.EvaluationRuntime(lambda slot: setting(policy_with("absolute_claim")), judge)
        report = runtime.evaluate(comparison_request())
        self.assertEqual(report["profiles"]["baseline"]["state"], "unavailable")
        self.assertNotIn("secret transport", json.dumps(report))
        request = comparison_request()
        for snapshot in request["responses"].values():
            snapshot["finish_reason"] = "insufficient_evidence"
        judge.reset_mock()
        report = runtime.evaluate(request)
        judge.assert_not_called()
        self.assertEqual(report["profiles"]["baseline"]["checks"][0]["outcome"], "not_applicable")
        request["responses"]["baseline"]["text"] = "tampered"
        with self.assertRaises(ValueError):
            runtime.evaluate(request)

    def test_large_evidence_budget_keeps_literal_findings_without_model_call(self):
        request = comparison_request()
        for slot, snapshot in request["responses"].items():
            document = snapshot["sources"][0]
            content = "Synthetic source text. " * 100
            snapshot["sources"] = [{**document, "id": f"{slot}:{number}", "content": content,
                                    "content_hash": evaluation.text_hash(content)} for number in range(1, 21)]
        self.assertGreater(len(evaluation.canonical_json(request).encode("utf-8")), 80000)
        policy = policy_with()
        policy["rules"].append(deepcopy(evaluation.RULE_TEMPLATES["absolute_claim"]))
        from unittest.mock import patch
        with patch.object(evaluation, "MAX_JUDGE_BYTES", 40000):
            report = self.run_evaluation(policy, request)
        self.assertEqual([check["outcome"] for check in report["profiles"]["baseline"]["checks"]], ["finding", "error"])
        self.assertEqual(report["usage"]["calls"], 0)
        self.judge.assert_not_called()

    def test_unfinished_generation_is_not_a_clean_factual_evaluation(self):
        request = comparison_request("Your cost is $50 after deductible.")
        request["responses"]["baseline"]["finish_reason"] = "length"
        checked = judge_check(outcome="no_finding", response_refs=[], evidence_refs=["baseline:1:passage:1"])
        report = self.run_evaluation(policy_with("fact_preservation"), request, judge_response(checked))
        self.assertEqual(report["profiles"]["baseline"]["state"], "partial")
        self.assertTrue(any("Generation did not finish" in warning for warning in report["profiles"]["baseline"]["warnings"]))

    def test_report_rejects_unmatched_quotes_and_false_completeness(self):
        request = comparison_request()
        report = self.run_evaluation(policy_with(), request)
        self.assertEqual(evaluation.validate_report(report, request), report)
        broken = deepcopy(report)
        broken["profiles"]["baseline"]["checks"][0]["response_quotes"][0]["quote"] = "invented"
        with self.assertRaises(ValueError):
            evaluation.validate_report(broken, request)
        broken = deepcopy(report)
        broken["profiles"]["baseline"]["checks"][0]["outcome"] = "not_verifiable"
        with self.assertRaises(ValueError):
            evaluation.validate_report(broken, request)

    def test_passage_selection_preserves_every_character_and_emits_exact_original_quotes(self):
        request = comparison_request("A hypothetical member asks about authorization. " * 15)
        original = deepcopy(request)
        policy = policy_with("unsupported_assurance")
        pending = [("candidate", policy["rules"][0])]
        context, references = evaluation._judge_context(request, pending)
        self.assertEqual(set(context["responses"]), {"candidate"})
        snapshot = request["responses"]["candidate"]
        view = context["responses"]["candidate"]
        self.assertEqual("".join(part["text"] for part in view["response_passages"]), snapshot["text"])
        self.assertEqual("".join(part["text"] for part in view["sources"][0]["passages"]), snapshot["sources"][0]["content"])
        self.assertTrue(all(0 < len(reference["text"]) <= 500 for reference in references.values()))
        checked = judge_check("candidate", response_refs=["candidate:response:passage:2"], evidence_refs=["candidate:1:passage:1"])
        report = self.run_evaluation(None, request, judge_response(checked), candidate=policy)
        accepted = report["profiles"]["candidate"]["checks"][0]
        self.assertEqual(accepted["outcome"], "finding")
        self.assertEqual(accepted["response_quotes"][0]["quote"], snapshot["text"][500:])
        self.assertEqual(accepted["evidence"][0]["quote"], snapshot["sources"][0]["content"])
        self.assertEqual(evaluation.validate_report(report, request), report)
        self.assertEqual(request, original)

    def test_known_passage_from_other_profile_or_wrong_reference_kind_is_rejected(self):
        request = comparison_request()
        policy = policy_with("unsupported_assurance")
        pending = [(slot, policy["rules"][0]) for slot in evaluation.PROFILE_SLOTS]
        _, references = evaluation._judge_context(request, pending)
        for overrides in (
            {"response_refs": ["baseline:response:passage:1"]},
            {"response_refs": ["candidate:1:passage:1"]},
            {"evidence_refs": ["baseline:1:passage:1"]},
            {"evidence_refs": ["candidate:response:passage:1"]},
            {"baseline_refs": ["baseline:response:passage:1"]},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                evaluation._resolve_judge_check(judge_check("candidate", **overrides), policy["rules"][0],
                    request["responses"]["candidate"], request["responses"]["baseline"], references)

    def test_supported_baseline_comparison_resolves_baseline_passage_references(self):
        policy = policy_with("fact_preservation")
        request = comparison_request("Your cost is $50 after deductible.")
        checked = judge_check("candidate", evidence_refs=["baseline:1:passage:1"], baseline_refs=["baseline:response:passage:1"])
        report = self.run_evaluation(None, request, judge_response(checked), candidate=policy)
        accepted = report["profiles"]["candidate"]["checks"][0]
        self.assertEqual(accepted["outcome"], "finding")
        self.assertEqual(accepted["baseline_quotes"][0]["quote"], request["responses"]["baseline"]["text"])
        self.assertEqual(accepted["evidence"][0]["source_id"], "baseline:1")


if __name__ == "__main__":
    unittest.main()