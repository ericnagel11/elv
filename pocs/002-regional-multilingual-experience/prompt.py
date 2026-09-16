"""Load a versioned Prompty asset for a market, render it, and call Azure OpenAI
with Entra ID authentication (no keys).

The change from proof of concept 001 is the resolution chain. Configuration
still names a behavior version (`response:v3`) and never names a locale, because
locale is a resolution step rather than part of the identifier. The most
specific asset that exists wins:

    prompts/response.v3.de-DE.prompty     market asset
    prompts/response.v3.de.prompty        language asset, shared by de-DE/de-AT/de-CH
    prompts/response.v3.prompty           neutral asset

This mirrors the label chain in market.py and has the same sparseness property.
A market asset is created only where the market must differ, so a version bump
to the neutral asset still reaches every market that has not deliberately
diverged. The chain that was tried is returned alongside the result, because
"which file answered this customer" is a question a reviewer will ask.

A localized asset is not a translation of the neutral one. It carries the
instructions that only make sense in that language: what formality means when
the language marks it grammatically, and the terminology that must not drift.
"""

import os
import re
import time
from functools import lru_cache

import yaml
from jinja2 import Template
from azure.identity import get_bearer_token_provider
from openai import AzureOpenAI

import rbac

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
_ROLE_RE = re.compile(r"^\s*(system|user|assistant)\s*:\s*$", re.IGNORECASE | re.MULTILINE)


@lru_cache(maxsize=1)
def _aoai_client() -> AzureOpenAI:
    token_provider = get_bearer_token_provider(rbac.service_credential("runtime"), COGNITIVE_SCOPE)
    return AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_ad_token_provider=token_provider,
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    )


def candidate_paths(asset_id: str, locale: str = "", language: str = "") -> list:
    """The files that would be tried, most specific first."""
    name, _, version = asset_id.partition(":")
    stem = f"{name}.{version}" if version else name
    suffixes = []
    if locale:
        suffixes.append(f".{locale}")
    if language and language != locale:
        suffixes.append(f".{language}")
    suffixes.append("")
    return [os.path.join(PROMPTS_DIR, f"{stem}{suffix}.prompty") for suffix in suffixes]


def resolve_asset(asset_id: str, locale: str = "", language: str = "") -> dict:
    """Pick the most specific asset that exists and report the whole attempt.

    The chain is returned even on success so the UI can show that a market fell
    back to the language or neutral asset. A silent fallback is the difference
    between "German customers get German instructions" and "we believed they
    did", and only one of those is checkable.
    """
    attempts = []
    chosen = None
    for path in candidate_paths(asset_id, locale, language):
        exists = os.path.exists(path)
        attempts.append({"file": os.path.basename(path), "exists": "yes" if exists else "no"})
        if exists and chosen is None:
            chosen = path
    if chosen is None:
        raise FileNotFoundError(
            f"No asset found for '{asset_id}'. Tried: "
            + ", ".join(item["file"] for item in attempts)
        )
    for item in attempts:
        item["used"] = "yes" if item["file"] == os.path.basename(chosen) else "no"
    return {"path": chosen, "file": os.path.basename(chosen), "attempts": attempts}


def _load_asset(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    _, front_matter, body = text.split("---", 2)
    return yaml.safe_load(front_matter) or {}, body


def _split_roles(body: str):
    markers = list(_ROLE_RE.finditer(body))
    if not markers:
        return [("system", body.strip())]
    segments = []
    preamble = body[: markers[0].start()].strip()
    if preamble:
        segments.append(("system", preamble))
    for index, marker in enumerate(markers):
        role = marker.group(1).lower()
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
        segments.append((role, body[start:end].strip()))
    return segments


def render_messages(body: str, inputs: dict) -> list:
    messages = []
    for role, content in _split_roles(body):
        rendered = Template(content).render(**inputs).strip()
        if rendered:
            messages.append({"role": role, "content": rendered})
    return messages


def generate_response(asset_id: str, inputs: dict, locale: str = "",
                      language: str = "") -> dict:
    resolution = resolve_asset(asset_id, locale, language)
    front_matter, body = _load_asset(resolution["path"])
    parameters = (front_matter.get("model") or {}).get("parameters") or {}
    messages = render_messages(body, inputs)

    started = time.perf_counter()
    # gpt-5 family models use max_completion_tokens (not max_tokens) and only the
    # default temperature; extra_body keeps this working across openai SDK versions.
    response = _aoai_client().chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=messages,
        extra_body={"max_completion_tokens": parameters.get("max_completion_tokens", 2000)},
    )
    elapsed = time.perf_counter() - started

    usage = response.usage
    return {
        "text": response.choices[0].message.content or "",
        "messages": messages,
        "asset": resolution["file"],
        "asset_attempts": resolution["attempts"],
        "latency_s": elapsed,
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
    }
