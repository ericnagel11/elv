"""Bounded, advisory response evaluation contracts and policy checks."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
import re
from time import monotonic
from uuid import uuid4

from openai import APIConnectionError, APIStatusError, APITimeoutError


POLICY_KEY = "rules:policy"
MAX_POLICY_BYTES = 8192
MAX_RULES = 10
PROFILE_SLOTS = ("baseline", "candidate")
SEVERITIES = ("high", "medium", "low")
EVIDENCE_EXTENSION = "https://contoso.example/a2a/extensions/evaluation-evidence/v1"
EVIDENCE_MEDIA_TYPE = "application/vnd.contoso.evaluation-evidence.v1+json"
MAX_ANSWER_CHARS = 16000
MAX_SNAPSHOT_BYTES = 256 * 1024
MAX_REQUEST_BYTES = 600 * 1024
MAX_JUDGE_BYTES = 96 * 1024
MAX_RESULT_BYTES = 160 * 1024
EVALUATOR_ASSET = "evaluation:v1"
REQUEST_MEDIA_TYPE = "application/vnd.contoso.evaluation-request.v1+json"
RESULT_MEDIA_TYPE = "application/vnd.contoso.evaluation-result.v1+json"
OUTCOMES = ("finding", "no_finding", "not_applicable", "not_verifiable", "error")
STATES = ("complete", "partial", "unavailable", "not_configured", "disabled", "no_active_rules")
_LOG = logging.getLogger(__name__)
_SEMANTIC_FAILURES = {
    "input_budget": "The supplied evidence exceeds the semantic evaluation input budget.",
    "model_request": "The evaluation model request failed or timed out.",
    "model_rate_limit": "Azure OpenAI rate-limited the evaluation request (HTTP 429). No automatic retry was made; retry after the service cooldown.",
    "model_timeout": "The evaluation model request timed out. No automatic retry was made.",
    "model_connection": "The evaluator could not connect to Azure OpenAI. Check the approved network route.",
    "model_authentication": "Azure OpenAI could not authenticate the evaluator (HTTP 401). Check the runtime identity configuration.",
    "model_authorization": "Azure OpenAI denied the evaluator request (HTTP 403). Check its approved identity and network access.",
    "model_not_found": "Azure OpenAI could not find the configured endpoint or deployment (HTTP 404).",
    "model_request_rejected": "Azure OpenAI rejected the evaluation request. Check the deployed model/API, structured-output schema and input limits.",
    "model_service": "Azure OpenAI reported a service failure. No automatic retry was made.",
    "model_finish": "The evaluation model did not return a complete judgment.",
    "output_json": "The evaluation model did not return valid JSON.",
    "output_schema": "The judgment did not contain the required fields and number of checks.",
    "rule_mapping": "The judgment returned an unexpected, duplicate or invalid rule reference.",
    "rule_evidence": "A judgment has invalid fields, quotations or source references.",
}
RULE_TEMPLATES = {
    "literal_phrase": {
        "id": "restricted-wording", "title": "Restricted wording", "type": "literal_phrase",
        "enabled": True, "severity": "medium",
        "criteria": "Flag these literal phrases, including when quoted or negated.",
        "parameters": {"terms": ["100% covered", "no cost"], "match": "phrase", "case_sensitive": False},
    },
    "absolute_claim": {
        "id": "absolute-coverage", "title": "Absolute cost or coverage claims", "type": "absolute_claim",
        "enabled": True, "severity": "high",
        "criteria": (
            "Flag unsupported unconditional cost or coverage assurances, including 100%, free, no cost, "
            "always, guaranteed or never. Distinguish negation and conditional wording. Check relevant "
            "network, preventive billing, deductible and separate ancillary-charge conditions against evidence."
        ),
        "parameters": {},
    },
    "unsupported_assurance": {
        "id": "authorization-assurance", "title": "Unsupported authorization or referral assurance",
        "type": "unsupported_assurance", "enabled": True, "severity": "high",
        "criteria": (
            "Flag categorical statements that prior authorization or a referral is not required without "
            "an explicit applicable determination. Missing information is not a negative determination. "
            "This demo has no member/CPT/site/provider determination service. General policy is not one."
        ),
        "parameters": {},
    },
    "fact_preservation": {
        "id": "preserve-conditions", "title": "Preserve costs, conditions and exclusions",
        "type": "fact_preservation", "enabled": True, "severity": "high",
        "criteria": (
            "Check that relevant evidence-backed costs, units, deductible conditions, limits and exclusions "
            "survive simplification. For example, $50 after deductible must not become $50. "
            "An unsupported baseline fact must not be imposed on the candidate."
        ),
        "parameters": {"compare_baseline": True},
    },
}


def _object(value, fields, name):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError(f"{name} has missing or unsupported fields.")


def _text(value, limit, name, *, empty=False):
    if type(value) is not str or len(value) > limit or "\x00" in value or (not empty and not value.strip()):
        raise ValueError(f"{name} must be bounded text.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError(f"{name} must contain valid Unicode.") from None
    return value


def _boolean(value, name):
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean.")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON fields are not allowed.")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Non-finite JSON numbers are not allowed.")


def strict_json(value, limit):
    _text(value, limit, "JSON")
    if len(value.encode("utf-8")) > limit:
        raise ValueError("JSON exceeds its byte limit.")
    try:
        return json.loads(value, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (json.JSONDecodeError, RecursionError):
        raise ValueError("Invalid JSON document.") from None


def canonical_json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("The document is not valid JSON data.") from None


def text_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_policy(policy):
    _object(policy, ("schema_version", "enabled", "rules"), "Rule policy")
    if type(policy["schema_version"]) is not int or policy["schema_version"] != 1:
        raise ValueError("Unsupported rule policy schema version.")
    _boolean(policy["enabled"], "Policy enabled")
    if type(policy["rules"]) is not list or len(policy["rules"]) > MAX_RULES:
        raise ValueError(f"A policy may contain at most {MAX_RULES} rules.")
    identifiers = set()
    for rule in policy["rules"]:
        _object(rule, ("id", "title", "type", "enabled", "severity", "criteria", "parameters"), "Rule")
        identifier = _text(rule["id"], 64, "Rule ID")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", identifier) or identifier in identifiers:
            raise ValueError("Rule IDs must be unique lowercase identifiers.")
        identifiers.add(identifier)
        _text(rule["title"], 120, "Rule title")
        _text(rule["criteria"], 800, "Rule criteria")
        _boolean(rule["enabled"], "Rule enabled")
        if type(rule["type"]) is not str or rule["type"] not in RULE_TEMPLATES:
            raise ValueError("Unsupported rule type.")
        if rule["severity"] not in SEVERITIES:
            raise ValueError("Unsupported rule severity.")
        parameters = rule["parameters"]
        if rule["type"] == "literal_phrase":
            _object(parameters, ("terms", "match", "case_sensitive"), "Literal parameters")
            terms = parameters["terms"]
            if type(terms) is not list or not 1 <= len(terms) <= 10:
                raise ValueError("Supply between 1 and 10 literal phrases.")
            for term in terms:
                _text(term, 80, "Literal phrase")
            if len(set(terms)) != len(terms):
                raise ValueError("Literal phrases must be unique.")
            if parameters["match"] not in ("phrase", "substring"):
                raise ValueError("Unsupported literal matching mode.")
            _boolean(parameters["case_sensitive"], "Case sensitive")
        elif rule["type"] == "fact_preservation":
            _object(parameters, ("compare_baseline",), "Preservation parameters")
            _boolean(parameters["compare_baseline"], "Compare baseline")
        else:
            _object(parameters, (), "Semantic parameters")
    if len(canonical_json(policy).encode("utf-8")) > MAX_POLICY_BYTES:
        raise ValueError("The rule policy exceeds 8192 UTF-8 bytes.")
    return deepcopy(policy)


def parse_policy(value):
    return validate_policy(strict_json(value, MAX_POLICY_BYTES))


def policy_json(policy):
    return canonical_json(validate_policy(policy))


def policy_revision(policy):
    return text_hash(policy_json(policy))


def literal_matches(text, rule):
    parameters = rule["parameters"]
    matches = {}
    for term in parameters["terms"]:
        pattern = re.escape(term)
        if parameters["match"] == "phrase":
            pattern = r"(?<!\w)" + pattern + r"(?!\w)"
        flags = 0 if parameters["case_sensitive"] else re.IGNORECASE
        for match in re.finditer(pattern, text, flags):
            matches[match.span()] = {"quote": match.group(), "start": match.start(), "end": match.end()}
    return [matches[span] for span in sorted(matches)][:20]


def _version(value):
    if type(value) not in (int, float) or value != 1:
        raise ValueError("Unsupported evaluation schema version.")


def validate_snapshot(snapshot, *, question=None, profile_slot=None):
    _object(snapshot, (
        "schema_version", "profile_slot", "task_id", "context_id", "question_hash", "text", "response_hash",
        "configuration_revision", "knowledge_revision", "prompt_asset", "grounded", "finish_reason",
        "citation_status", "evidence_status", "sources",
    ), "Response snapshot")
    _version(snapshot["schema_version"])
    slot = snapshot["profile_slot"]
    if slot not in PROFILE_SLOTS or (profile_slot is not None and slot != profile_slot):
        raise ValueError("The response snapshot has the wrong profile.")
    for field in ("task_id", "context_id", "configuration_revision", "knowledge_revision", "prompt_asset"):
        _text(snapshot[field], 160, field, empty=field == "knowledge_revision")
    _text(snapshot["text"], MAX_ANSWER_CHARS, "Response text")
    _text(snapshot["finish_reason"], 80, "Finish reason")
    _text(snapshot["citation_status"], 80, "Citation status")
    for field in ("response_hash", "question_hash"):
        if not re.fullmatch(r"[0-9a-f]{64}", _text(snapshot[field], 64, field)):
            raise ValueError("Invalid snapshot hash.")
    if snapshot["response_hash"] != text_hash(snapshot["text"]):
        raise ValueError("The response hash does not match its text.")
    if question is not None and snapshot["question_hash"] != text_hash(question.strip()):
        raise ValueError("The snapshot belongs to a different question.")
    _boolean(snapshot["grounded"], "Grounded")
    if snapshot["evidence_status"] not in ("available", "none", "unavailable"):
        raise ValueError("Invalid evidence status.")
    sources = snapshot["sources"]
    if type(sources) is not list or len(sources) > 20:
        raise ValueError("A snapshot may contain at most 20 sources.")
    if sources and (not snapshot["grounded"] or snapshot["evidence_status"] != "available"):
        raise ValueError("Source evidence does not match the generation state.")
    if snapshot["evidence_status"] == "available" and not sources:
        raise ValueError("Available evidence requires source excerpts.")
    for position, source in enumerate(sources, start=1):
        _object(source, ("id", "title", "content", "content_hash", "truncated", "status", "state", "effective_date"), "Source")
        if source["id"] != f"{slot}:{position}":
            raise ValueError("Source IDs must preserve their profile and order.")
        _text(source["content"], 2500, "Source content")
        if source["content_hash"] != text_hash(source["content"]):
            raise ValueError("The source hash does not match its content.")
        _boolean(source["truncated"], "Source truncated")
        for field, limit in (("title", 512), ("status", 100), ("state", 100), ("effective_date", 100)):
            _text(source[field], limit, field, empty=True)
    if len(canonical_json(snapshot).encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ValueError("The evidence snapshot exceeds its byte limit.")
    return {**deepcopy(snapshot), "schema_version": 1}


def build_snapshot(bundle, task_id, context_id, question):
    slot = bundle["profile_slot"]
    text = bundle["result"]["text"]
    grounded = bool(bundle.get("grounded"))
    snapshot = {
        "schema_version": 1, "profile_slot": slot, "task_id": task_id, "context_id": context_id,
        "question_hash": text_hash(question.strip()), "text": text, "response_hash": text_hash(text),
        "configuration_revision": bundle["configuration_revision"],
        "knowledge_revision": bundle.get("knowledge_revision", ""), "prompt_asset": bundle["prompt_asset"],
        "grounded": grounded, "finish_reason": bundle["result"].get("finish_reason") or "unknown",
        "citation_status": bundle.get("citation_status", "not_checked"),
        "evidence_status": "none", "sources": [],
    }
    if grounded:
        try:
            snapshot["sources"] = [
                {"id": f"{slot}:{position}", "title": document.get("title", ""),
                 "content": document["content"], "content_hash": text_hash(document["content"]),
                 "truncated": document.get("truncated", False), "status": document.get("status", ""),
                 "state": document.get("state", ""), "effective_date": document.get("effective_date", "")}
                for position, document in enumerate(bundle["found"]["documents"], start=1)
            ]
            snapshot["evidence_status"] = "available"
            return validate_snapshot(snapshot, question=question)
        except (ValueError, KeyError, TypeError, UnicodeError):
            snapshot.update(sources=[], evidence_status="unavailable")
    return validate_snapshot(snapshot, question=question)


def validate_request(payload):
    _object(payload, ("schema_version", "comparison_id", "question", "responses"), "Evaluation request")
    _version(payload["schema_version"])
    _text(payload["comparison_id"], 128, "Comparison ID")
    _text(payload["question"], 8000, "Question")
    _object(payload["responses"], PROFILE_SLOTS, "Comparison responses")
    responses = {
        slot: validate_snapshot(payload["responses"][slot], question=payload["question"], profile_slot=slot)
        for slot in PROFILE_SLOTS
    }
    if responses["baseline"]["task_id"] == responses["candidate"]["task_id"]:
        raise ValueError("Comparison responses must come from distinct tasks.")
    if len(canonical_json(payload).encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ValueError("The evaluation request exceeds its byte limit.")
    return {**deepcopy(payload), "schema_version": 1, "responses": responses}


def _check(rule, outcome, reason, *, response_quotes=None, evidence=None, baseline_quotes=None):
    return {
        "rule_id": rule["id"], "title": rule["title"], "type": rule["type"], "severity": rule["severity"],
        "outcome": outcome, "reason": reason, "response_quotes": response_quotes or [],
        "evidence": evidence or [], "baseline_quotes": baseline_quotes or [],
    }


def _quotes(values, text):
    if type(values) is not list or len(values) > 5:
        raise ValueError("Invalid quoted spans.")
    result = []
    for quote in values:
        _text(quote, 500, "Quoted text")
        start = text.find(quote)
        if start < 0:
            raise ValueError("A quoted span is not present in its response.")
        result.append({"quote": quote, "start": start, "end": start + len(quote)})
    return result


def _semantic_check(item, rule, snapshot, baseline):
    _object(item, ("profile_slot", "rule_id", "outcome", "reason", "response_quotes", "evidence", "baseline_quotes"), "Judge check")
    if item["profile_slot"] != snapshot["profile_slot"] or item["rule_id"] != rule["id"]:
        raise ValueError("The judge returned a different rule or profile.")
    if item["outcome"] not in OUTCOMES:
        raise ValueError("Unsupported evaluation outcome.")
    _text(item["reason"], 800, "Evaluation reason")
    response_quotes = _quotes(item["response_quotes"], snapshot["text"])
    use_baseline = (rule["type"] == "fact_preservation" and rule["parameters"]["compare_baseline"]
                    and snapshot["profile_slot"] == "candidate")
    if item["baseline_quotes"] and not use_baseline:
        raise ValueError("This rule does not permit baseline comparison.")
    baseline_quotes = _quotes(item["baseline_quotes"], baseline["text"])
    sources = {source["id"]: source for source in snapshot["sources"]}
    if use_baseline:
        sources.update({source["id"]: source for source in baseline["sources"]})
    if type(item["evidence"]) is not list or len(item["evidence"]) > 5:
        raise ValueError("Invalid evaluation evidence references.")
    for reference in item["evidence"]:
        _object(reference, ("source_id", "quote"), "Evidence reference")
        _text(reference["source_id"], 80, "Source ID")
        _text(reference["quote"], 500, "Evidence quote")
        source = sources.get(reference["source_id"])
        if source is None or reference["quote"] not in source["content"]:
            raise ValueError("An evidence reference does not match a supplied source.")
    outcome, reason = item["outcome"], item["reason"]
    if outcome == "finding" and not response_quotes and not item["evidence"]:
        raise ValueError("A finding needs a response quote or omission evidence.")
    if rule["type"] == "fact_preservation" and outcome in ("finding", "no_finding") and not item["evidence"]:
        raise ValueError("Fact preservation needs quoted source support, not baseline wording alone.")
    if outcome == "no_finding":
        incomplete = (snapshot["finish_reason"] != "stop" or snapshot["evidence_status"] != "available"
                      or any(source["truncated"] for source in sources.values()))
        if rule["type"] == "unsupported_assurance":
            outcome, reason = "not_verifiable", "No authoritative member-specific authorization or referral determination is available."
        elif incomplete or not item["evidence"]:
            outcome, reason = "not_verifiable", "Available evidence cannot establish complete support for this check."
    return _check(rule, outcome, reason, response_quotes=response_quotes,
                  evidence=deepcopy(item["evidence"]), baseline_quotes=baseline_quotes)


def _judge_context(request, pending):
    references = {}
    slots = {slot for slot, _rule in pending}
    if any(slot == "candidate" and rule["type"] == "fact_preservation" and rule["parameters"]["compare_baseline"]
           for slot, rule in pending):
        slots.add("baseline")

    def passages(text, prefix, slot, source_id=None):
        result = []
        for start in range(0, len(text), 500):
            identifier = f"{prefix}:passage:{len(result) + 1}"
            original = text[start:start + 500]
            references[identifier] = {"profile_slot": slot, "source_id": source_id, "text": original}
            result.append({"id": identifier, "text": original})
        return result

    responses = {}
    for slot in sorted(slots):
        snapshot = request["responses"][slot]
        view = {key: value for key, value in snapshot.items() if key not in ("text", "sources")}
        view["response_passages"] = passages(snapshot["text"], f"{slot}:response", slot)
        view["sources"] = []
        for source in snapshot["sources"]:
            view["sources"].append({
                **{key: value for key, value in source.items() if key != "content"},
                "passages": passages(source["content"], source["id"], slot, source["id"]),
            })
        responses[slot] = view
    return {
        "question": request["question"], "responses": responses,
        "checks": [{"profile_slot": slot, "rule": rule} for slot, rule in pending],
    }, references


def _resolve_judge_check(item, rule, snapshot, baseline, references):
    _object(item, ("profile_slot", "rule_id", "outcome", "reason", "response_refs", "evidence_refs", "baseline_refs"), "Judge check")
    allow_baseline = (snapshot["profile_slot"] == "candidate" and rule["type"] == "fact_preservation"
                      and rule["parameters"]["compare_baseline"])

    def resolve(field):
        values = item[field]
        if values is None:
            return []
        if type(values) is not list or len(values) > 5:
            raise ValueError("Invalid judgment passage references.")
        resolved = []
        for identifier in values:
            _text(identifier, 100, "Passage ID")
            reference = references.get(identifier)
            if reference is None:
                raise ValueError("An unknown passage was referenced.")
            if field == "response_refs":
                valid = reference["profile_slot"] == snapshot["profile_slot"] and reference["source_id"] is None
            elif field == "baseline_refs":
                valid = allow_baseline and reference["profile_slot"] == "baseline" and reference["source_id"] is None
            else:
                valid = reference["source_id"] is not None and (
                    reference["profile_slot"] == snapshot["profile_slot"] or (allow_baseline and reference["profile_slot"] == "baseline")
                )
            if not valid:
                raise ValueError("A passage is outside the rule's response or evidence scope.")
            resolved.append(reference)
        return resolved

    normalized = {key: item[key] for key in ("profile_slot", "rule_id", "outcome", "reason")}
    normalized.update(
        response_quotes=[reference["text"] for reference in resolve("response_refs")],
        evidence=[{"source_id": reference["source_id"], "quote": reference["text"]} for reference in resolve("evidence_refs")],
        baseline_quotes=[reference["text"] for reference in resolve("baseline_refs")],
    )
    return _semantic_check(normalized, rule, snapshot, baseline)


def _model_failure_stage(problem):
    if isinstance(problem, (APITimeoutError, TimeoutError)):
        return "model_timeout"
    if isinstance(problem, APIConnectionError):
        return "model_connection"
    if isinstance(problem, APIStatusError):
        status = problem.status_code
        stages = {
            401: "model_authentication", 403: "model_authorization", 404: "model_not_found",
            408: "model_timeout", 429: "model_rate_limit",
        }
        if status in stages:
            return stages[status]
        if 400 <= status < 500:
            return "model_request_rejected"
        if 500 <= status < 600:
            return "model_service"
    return "model_request"


def _model_retry_hint(problem):
    if not isinstance(problem, APIStatusError) or problem.status_code not in (429, 503):
        return ""
    for header, scale in (("retry-after", 1), ("retry-after-ms", 1000)):
        value = problem.response.headers.get(header, "")
        if value.isascii() and value.isdecimal() and len(value) <= 10:
            seconds = (int(value) + scale - 1) // scale
            if 0 < seconds <= 86400:
                return f" Retry after at least {seconds} seconds."
    return ""


def judge_response_format(pending, references):
    """Constrain model output shape; exact counts and evidence remain locally checked."""
    slots = {slot for slot, _rule in pending}
    allow_baseline = any(slot == "candidate" and rule["type"] == "fact_preservation" and rule["parameters"]["compare_baseline"]
                         for slot, rule in pending)

    def reference_array(identifiers):
        return {"type": "array", "items": {"type": "string", "enum": identifiers}} if identifiers else {"type": "null"}

    properties = {
        "profile_slot": {"type": "string", "enum": sorted(slots)},
        "rule_id": {"type": "string", "enum": sorted({rule["id"] for _slot, rule in pending})},
        "outcome": {"type": "string", "enum": list(OUTCOMES)},
        "reason": {"type": "string"},
        "response_refs": reference_array([identifier for identifier, reference in references.items()
                                           if reference["profile_slot"] in slots and reference["source_id"] is None]),
        "evidence_refs": reference_array([identifier for identifier, reference in references.items() if reference["source_id"] is not None]),
        "baseline_refs": reference_array([identifier for identifier, reference in references.items()
                                           if allow_baseline and reference["profile_slot"] == "baseline" and reference["source_id"] is None]),
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "advisory_evaluation_v1", "strict": True,
            "schema": {
                "type": "object",
                "properties": {"checks": {
                    "type": "array",
                    "description": f"Exactly {len(pending)} checks, one for each requested profile_slot and rule.id pair, without duplicates.",
                    "items": {"type": "object", "properties": properties,
                              "required": list(properties), "additionalProperties": False},
                }},
                "required": ["checks"], "additionalProperties": False,
            },
        },
    }


class EvaluationRuntime:
    """Resolve current policies and assess immutable responses without modifying them."""

    def __init__(self, policy_loader=None, judge=None):
        if policy_loader is None:
            from config import load_rule_policy
            policy_loader = load_rule_policy
        if judge is None:
            from prompt import generate_response
            judge = generate_response
        self.policy_loader = policy_loader
        self.judge = judge

    def evaluate(self, payload):
        request = validate_request(payload)
        started = monotonic()
        report = {
            "schema_version": 1, "comparison_id": request["comparison_id"], "evaluation_id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(), "evaluator_prompt": EVALUATOR_ASSET,
            "deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT", "not_reported"), "model": "not_called",
            "latency_s": 0, "usage": {"calls": 0, "prompt_tokens": None, "completion_tokens": None}, "profiles": {},
        }
        pending = []
        policies = {}
        baseline = request["responses"]["baseline"]
        for slot, snapshot in request["responses"].items():
            profile = {
                "state": "unavailable", "policy_etag": None, "policy_revision": None, "active_rules": 0,
                "response_task_id": snapshot["task_id"], "response_hash": snapshot["response_hash"],
                "configuration_revision": snapshot["configuration_revision"], "checks": [], "warnings": [],
            }
            report["profiles"][slot] = profile
            try:
                setting = self.policy_loader(slot)
                if setting["policy"] is None:
                    profile["state"] = "not_configured"
                    continue
                policy = validate_policy(setting["policy"])
                _text(setting["etag"], 200, "Policy ETag")
                profile.update(policy_etag=setting["etag"], policy_revision=policy_revision(policy))
            except Exception:
                profile["warnings"].append("The current rule policy could not be loaded or validated. No cached policy was used.")
                continue
            if not policy["enabled"]:
                profile["state"] = "disabled"
                continue
            rules = [rule for rule in policy["rules"] if rule["enabled"]]
            profile["active_rules"] = len(rules)
            policies[slot] = rules
            if not rules:
                profile["state"] = "no_active_rules"
                continue
            profile["state"] = "complete"
            if snapshot["finish_reason"] not in ("stop", "no_sources", "insufficient_evidence", "citation_validation_failed"):
                profile["warnings"].append("Generation did not finish normally; only the available response text can be assessed.")
            if snapshot["evidence_status"] != "available":
                profile["warnings"].append("Source evidence is absent or unavailable; factual support is limited.")
            elif any(source["truncated"] for source in snapshot["sources"]):
                profile["warnings"].append("Some source excerpts were truncated; evaluation does not establish complete policy coverage.")
            for rule in rules:
                if snapshot["finish_reason"] in ("no_sources", "insufficient_evidence", "citation_validation_failed"):
                    profile["checks"].append(_check(rule, "not_applicable", "The runtime returned an abstention or withheld-answer notice, not a model answer."))
                elif rule["type"] == "literal_phrase":
                    matches = literal_matches(snapshot["text"], rule)
                    profile["checks"].append(_check(rule, "finding" if matches else "no_finding",
                        "Configured literal wording was found (including quoted or negated uses)." if matches else "No configured literal phrase was found.",
                        response_quotes=matches))
                elif rule["type"] == "fact_preservation" and snapshot["evidence_status"] != "available":
                    profile["checks"].append(_check(rule, "not_verifiable", "Fact preservation requires applicable source excerpts."))
                elif (rule["type"] == "fact_preservation" and slot == "candidate" and rule["parameters"]["compare_baseline"]
                      and (not snapshot["knowledge_revision"] or snapshot["knowledge_revision"] != baseline["knowledge_revision"]
                           or baseline["evidence_status"] != "available")):
                    profile["checks"].append(_check(rule, "not_verifiable", "Baseline comparison requires compatible knowledge scopes and available baseline evidence."))
                else:
                    pending.append((slot, rule))
        if pending:
            failure_stage = "input_budget"
            try:
                judge_input, references = _judge_context(request, pending)
                encoded = canonical_json(judge_input)
                if len(encoded.encode("utf-8")) > MAX_JUDGE_BYTES:
                    raise ValueError("Evaluation evidence exceeds the judge budget.")
                failure_stage = "model_request"
                report["usage"]["calls"] = 1
                report["model"] = "not_reported"
                judged = self.judge(
                    EVALUATOR_ASSET, {"evaluation_input": encoded}, timeout_s=35.0, max_retries=0,
                    response_format=judge_response_format(pending, references),
                )
                failure_stage = "model_finish"
                report["usage"].update(prompt_tokens=judged.get("prompt_tokens"), completion_tokens=judged.get("completion_tokens"))
                report["model"] = judged.get("model") or "not_reported"
                if judged.get("finish_reason") != "stop":
                    raise ValueError("The judge did not finish a complete result.")
                failure_stage = "output_json"
                parsed = strict_json(judged["text"], MAX_RESULT_BYTES)
                failure_stage = "output_schema"
                _object(parsed, ("checks",), "Judge output")
                if type(parsed["checks"]) is not list or len(parsed["checks"]) != len(pending):
                    raise ValueError("The judge did not report every requested check.")
                expected = {(slot, rule["id"]): rule for slot, rule in pending}
                checked = {}
                for item in parsed["checks"]:
                    failure_stage = "rule_mapping"
                    if type(item) is not dict or type(item.get("profile_slot")) is not str or type(item.get("rule_id")) is not str:
                        raise ValueError("Invalid judge rule reference.")
                    identity = (item["profile_slot"], item["rule_id"])
                    if identity not in expected or identity in checked:
                        raise ValueError("The judge returned an unexpected or duplicate check.")
                    failure_stage = "rule_evidence"
                    checked[identity] = _resolve_judge_check(item, expected[identity], request["responses"][identity[0]], baseline, references)
                for (slot, _identifier), check in checked.items():
                    report["profiles"][slot]["checks"].append(check)
            except Exception as problem:
                retry_hint = ""
                if failure_stage == "model_request":
                    failure_stage = _model_failure_stage(problem)
                    retry_hint = _model_retry_hint(problem)
                _LOG.warning("Semantic evaluation failed: evaluation_id=%s stage=%s", report["evaluation_id"], failure_stage)
                reason = f"Semantic evaluation failed [{failure_stage}]. {_SEMANTIC_FAILURES[failure_stage]}{retry_hint} No conclusion was accepted."
                for slot, rule in pending:
                    report["profiles"][slot]["checks"].append(_check(rule, "error", reason))
        for slot, rules in policies.items():
            profile = report["profiles"][slot]
            order = {rule["id"]: position for position, rule in enumerate(rules)}
            profile["checks"].sort(key=lambda check: order[check["rule_id"]])
            incomplete = sum(check["outcome"] in ("error", "not_verifiable") for check in profile["checks"])
            if incomplete:
                profile["state"] = "unavailable" if all(check["outcome"] == "error" for check in profile["checks"]) else "partial"
        report["latency_s"] = round(monotonic() - started, 3)
        return report


def _integer(value, maximum, name):
    if type(value) not in (int, float) or not 0 <= value <= maximum or not math.isfinite(value) or value != int(value):
        raise ValueError(f"Invalid {name}.")
    return int(value)


def validate_report(report, request):
    _object(report, ("schema_version", "comparison_id", "evaluation_id", "timestamp", "evaluator_prompt",
                     "deployment", "model", "latency_s", "usage", "profiles"), "Evaluation report")
    _version(report["schema_version"])
    if report["comparison_id"] != request["comparison_id"] or report["evaluator_prompt"] != EVALUATOR_ASSET:
        raise ValueError("Evaluation report correlation failed.")
    for field in ("evaluation_id", "timestamp", "deployment", "model"):
        _text(report[field], 200, field)
    if type(report["latency_s"]) not in (int, float) or not math.isfinite(report["latency_s"]) or report["latency_s"] < 0:
        raise ValueError("Invalid evaluation latency.")
    _object(report["usage"], ("calls", "prompt_tokens", "completion_tokens"), "Evaluation usage")
    _integer(report["usage"]["calls"], 1, "judge call count")
    for field in ("prompt_tokens", "completion_tokens"):
        if report["usage"][field] is not None:
            _integer(report["usage"][field], 1_000_000, field)
    _object(report["profiles"], PROFILE_SLOTS, "Evaluation profiles")
    normalized = deepcopy(report)
    for slot, profile in normalized["profiles"].items():
        snapshot = request["responses"][slot]
        _object(profile, ("state", "policy_etag", "policy_revision", "active_rules", "response_task_id", "response_hash",
                          "configuration_revision", "checks", "warnings"), "Profile evaluation")
        if profile["state"] not in STATES:
            raise ValueError("Invalid evaluation state.")
        for field, original in (("response_task_id", "task_id"), ("response_hash", "response_hash"), ("configuration_revision", "configuration_revision")):
            if profile[field] != snapshot[original]:
                raise ValueError("An evaluation is attached to the wrong response.")
        for field in ("policy_etag", "policy_revision"):
            if profile[field] is not None:
                _text(profile[field], 200, field)
        active = _integer(profile["active_rules"], MAX_RULES, "active rule count")
        if type(profile["checks"]) is not list or len(profile["checks"]) != active:
            raise ValueError("The report must account for every active rule.")
        if active and (not profile["policy_etag"] or not profile["policy_revision"]):
            raise ValueError("Evaluated rules require a policy revision.")
        if profile["state"] in ("not_configured", "disabled", "no_active_rules") and active:
            raise ValueError("Inactive policies cannot contain evaluated rules.")
        if profile["state"] == "complete" and (not active or any(check.get("outcome") in ("error", "not_verifiable") for check in profile["checks"] if isinstance(check, dict))):
            raise ValueError("Incomplete evaluation cannot be reported as complete.")
        if type(profile["warnings"]) is not list or len(profile["warnings"]) > 10:
            raise ValueError("Invalid evaluation warnings.")
        for warning in profile["warnings"]:
            _text(warning, 800, "Evaluation warning")
        seen = set()
        for check in profile["checks"]:
            _object(check, ("rule_id", "title", "type", "severity", "outcome", "reason", "response_quotes", "evidence", "baseline_quotes"), "Rule result")
            identifier = _text(check["rule_id"], 64, "Rule ID")
            if identifier in seen or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", identifier):
                raise ValueError("Invalid or repeated result rule ID.")
            seen.add(identifier)
            _text(check["title"], 120, "Rule title")
            _text(check["reason"], 800, "Rule reason")
            if type(check["type"]) is not str or check["type"] not in RULE_TEMPLATES or check["severity"] not in SEVERITIES or check["outcome"] not in OUTCOMES:
                raise ValueError("Invalid rule result classification.")
            for field, text in (("response_quotes", snapshot["text"]), ("baseline_quotes", request["responses"]["baseline"]["text"])):
                if type(check[field]) is not list or len(check[field]) > (20 if check["type"] == "literal_phrase" else 5):
                    raise ValueError("Invalid result quotations.")
                for span in check[field]:
                    _object(span, ("quote", "start", "end"), "Result quote")
                    _text(span["quote"], 500, "Result quote")
                    start = _integer(span["start"], len(text), "quote start")
                    end = _integer(span["end"], len(text), "quote end")
                    if text[start:end] != span["quote"]:
                        raise ValueError("A result quotation is not an exact response span.")
                    span.update(start=start, end=end)
            sources = {source["id"]: source for source in snapshot["sources"]}
            peer_allowed = (slot == "candidate" and check["type"] == "fact_preservation"
                            and snapshot["knowledge_revision"] and snapshot["knowledge_revision"] == request["responses"]["baseline"]["knowledge_revision"])
            if peer_allowed:
                sources.update({source["id"]: source for source in request["responses"]["baseline"]["sources"]})
            elif check["baseline_quotes"]:
                raise ValueError("Unexpected baseline quotations.")
            if type(check["evidence"]) is not list or len(check["evidence"]) > 5:
                raise ValueError("Invalid result evidence.")
            for reference in check["evidence"]:
                _object(reference, ("source_id", "quote"), "Result reference")
                _text(reference["source_id"], 80, "Result source")
                _text(reference["quote"], 500, "Result evidence quote")
                source = sources.get(reference["source_id"])
                if source is None or reference["quote"] not in source["content"]:
                    raise ValueError("A result references evidence not supplied for this profile.")
    if len(canonical_json(report).encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("Evaluation report exceeds its byte limit.")
    return normalized