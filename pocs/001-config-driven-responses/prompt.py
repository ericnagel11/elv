"""Load a versioned Prompty asset, render it with configuration values, and call
Azure OpenAI with Entra ID authentication (no keys).

The `.prompty` files under prompts/ are the prompt assets. Their bodies are
Jinja2 templates whose variables (tone, verbosity, reading_level,
response_structure, persona, user_message) come from Azure App Configuration and
the user's message. This keeps the wording configurable without a code release.
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


def _asset_path(asset_id: str) -> str:
    # asset_id looks like "response:v2" -> prompts/response.v2.prompty
    name, _, version = asset_id.partition(":")
    return os.path.join(PROMPTS_DIR, f"{name}.{version}.prompty")


def _load_asset(asset_id: str):
    with open(_asset_path(asset_id), "r", encoding="utf-8") as handle:
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


def generate_response(asset_id: str, inputs: dict) -> dict:
    front_matter, body = _load_asset(asset_id)
    parameters = (front_matter.get("model") or {}).get("parameters") or {}
    messages = render_messages(body, inputs)

    started = time.perf_counter()
    # gpt-5 family models use max_completion_tokens (not max_tokens) and only the
    # default temperature; extra_body keeps this working across openai SDK versions.
    # That budget also covers hidden reasoning tokens, so reasoning_effort is sent
    # alongside it to stop reasoning from consuming the whole allowance.
    extra_body = {"max_completion_tokens": parameters.get("max_completion_tokens", 3000)}
    if parameters.get("reasoning_effort"):
        extra_body["reasoning_effort"] = parameters["reasoning_effort"]
    response = _aoai_client().chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=messages,
        extra_body=extra_body,
    )
    elapsed = time.perf_counter() - started

    choice = response.choices[0]
    usage = response.usage
    details = getattr(usage, "completion_tokens_details", None) if usage else None
    return {
        "text": choice.message.content or "",
        "messages": messages,
        "latency_s": elapsed,
        "finish_reason": choice.finish_reason,
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
        "reasoning_tokens": getattr(details, "reasoning_tokens", None) if details else None,
    }
