"""Language adherence: the guardrail for the failure this design invites.

Models occasionally answer in the wrong language, and they do it most often in
exactly the situation this proof of concept creates: retrieved context in one
language, instructions in another, and a customer question somewhere in between.
A German customer receiving a fluent English answer is not a subtle degradation.
It is a service failure that no amount of prompt review catches, because it does
not happen every time.

Detecting the response language and comparing it to the market's expected
language turns that into something observable. What happens next is
configuration rather than code, because the right answer differs by market:

  market:language_adherence = enforce   suppress the answer and offer a handoff
  market:language_adherence = warn      return the answer and record the mismatch
  market:language_adherence = off       do not check

Azure AI Language is an optional layer here, matching how the knowledge and
governance layers are optional in proof of concept 001. Without it the guardrail
reports as unavailable rather than failing the request, so the rest of the
demonstration still runs.
"""

import os
from functools import lru_cache

from azure.core.exceptions import HttpResponseError
from azure.ai.textanalytics import TextAnalyticsClient
from azure.identity import DefaultAzureCredential

ENDPOINT_ENV = "AZURE_LANGUAGE_ENDPOINT"

# Below this the detector is guessing, usually because the text is short or is a
# proper noun. Treating a guess as a mismatch would produce false failures on
# perfectly good answers.
MIN_CONFIDENCE = 0.7

ENFORCE = "enforce"
WARN = "warn"
OFF = "off"
MODES = [ENFORCE, WARN, OFF]


def endpoint() -> str:
    return os.environ.get(ENDPOINT_ENV, "")


def configured() -> bool:
    return bool(endpoint())


@lru_cache(maxsize=1)
def _client() -> TextAnalyticsClient:
    return TextAnalyticsClient(endpoint=endpoint(), credential=DefaultAzureCredential())


def mode_of(profile: dict) -> str:
    mode = str((profile or {}).get("language_adherence", WARN)).strip().lower()
    return mode if mode in MODES else WARN


def check(text: str, expected_language: str, mode: str = WARN) -> dict:
    """Compare the language of a generated answer with the market's language.

    Returns a verdict rather than raising, because whether a mismatch should
    stop the answer is a configured business decision and not this module's to
    make.
    """
    verdict = {
        "mode": mode,
        "expected": expected_language,
        "detected": "",
        "confidence": None,
        "status": "skipped",
        "message": "",
        "suppress": False,
    }

    if mode == OFF:
        verdict["message"] = "The guardrail is switched off for this market."
        return verdict

    if not configured():
        verdict["status"] = "unavailable"
        verdict["message"] = (
            "Azure AI Language is not provisioned, so the response language was not "
            "verified. Run scripts/setup-language.ps1 to enable this check."
        )
        return verdict

    body = (text or "").strip()
    if not body:
        verdict["message"] = "There was no text to check."
        return verdict

    try:
        result = _client().detect_language([{"id": "1", "text": body[:5000]}])[0]
    except HttpResponseError as exc:
        verdict["status"] = "unavailable"
        verdict["message"] = f"Language detection failed: {(exc.message or '').strip()}"
        return verdict

    if getattr(result, "is_error", False):
        verdict["status"] = "unavailable"
        verdict["message"] = "Language detection returned an error for this text."
        return verdict

    detected = (result.primary_language.iso6391_name or "").lower()
    confidence = result.primary_language.confidence_score
    verdict["detected"] = detected
    verdict["confidence"] = round(confidence, 3)

    if confidence < MIN_CONFIDENCE:
        verdict["status"] = "inconclusive"
        verdict["message"] = (
            f"Detected '{detected}' with low confidence ({confidence:.2f}), which is "
            "not a strong enough signal to act on."
        )
        return verdict

    if detected == (expected_language or "").lower():
        verdict["status"] = "match"
        verdict["message"] = f"The answer is in '{detected}', as this market expects."
        return verdict

    verdict["status"] = "mismatch"
    verdict["suppress"] = mode == ENFORCE
    verdict["message"] = (
        f"The answer is in '{detected}' but this market expects '{expected_language}'. "
        + ("The answer was withheld and the customer should be handed off."
           if mode == ENFORCE else
           "The answer was returned and the mismatch recorded, because this market "
           "is configured to warn rather than enforce.")
    )
    return verdict
