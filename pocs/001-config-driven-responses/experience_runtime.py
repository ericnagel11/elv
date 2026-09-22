"""UI-independent runtime for configured conversational responses."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Callable

import config as cfg
import knowledge
from prompt import generate_response

ALLOWED_PROFILE_SLOTS = frozenset(cfg.PROFILE_LABELS)
GROUNDED_ASSET = "response:v3"
SEARCH_DISABLED_NOTE = (
    "Search grounding is disabled by configuration. "
    "This response uses the experience prompt without Search references."
)


def _revision(profile: dict, scope: dict | None = None) -> str:
    payload = {"profile": profile, "scope": scope or {}}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def run_variant(profile: dict, user_message: str) -> dict:
    asset_id = profile.get("prompt_asset", "response:v1")
    inputs = {key: value for key, value in profile.items() if key != "prompt_asset"}
    inputs["user_message"] = user_message
    return generate_response(asset_id, inputs)


def run_grounded(
    experience_profile: dict,
    scope: dict,
    question: str,
    persona: str,
) -> dict:
    """Honor configured grounding, including for direct UI preview callers.

    Keep result/found compatible with the UI. The additive grounded flag means
    references were actually retrieved, not just that grounding was requested.
    Missing Search configuration uses v3's no-reference rules, not invented
    plan facts or an assertion of successful grounding.
    """
    scope = knowledge.settings_from_profile(scope)
    if not knowledge.is_enabled(scope):
        return {
            "result": run_variant(experience_profile, question),
            "found": {"documents": [], "notes": [SEARCH_DISABLED_NOTE], "index": None},
            "grounded": False,
        }
    if not knowledge.configured():
        found = {
            "documents": [],
            "notes": [
                "Search grounding is unavailable: AZURE_SEARCH_ENDPOINT is not configured. "
                "No Search request was made and no reference material is available."
            ],
            "index": None,
        }
    else:
        found = knowledge.search(question, scope, persona)
    inputs = {
        key: value
        for key, value in experience_profile.items()
        if key != "prompt_asset"
    }
    inputs["user_message"] = question
    inputs["citation_style"] = scope.get("citation_style", "inline")
    inputs["context"] = knowledge.format_context(
        found["documents"], scope.get("citation_style")
    )
    return {
        "result": generate_response(GROUNDED_ASSET, inputs),
        "found": found,
        "grounded": bool(found["documents"]),
    }


@dataclass(frozen=True)
class ContextBinding:
    profile_slot: str
    profile: dict
    knowledge_scope: dict
    revision: str


class ContextBindings:
    """Pin resolved configuration to an A2A context for conversational coherence."""

    def __init__(self) -> None:
        self._bindings: dict[str, ContextBinding] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        context_id: str,
        profile_slot: str,
        resolver: Callable[[str], ContextBinding],
    ) -> ContextBinding:
        if profile_slot not in ALLOWED_PROFILE_SLOTS:
            allowed = ", ".join(sorted(ALLOWED_PROFILE_SLOTS))
            raise ValueError(f"profile_slot must be one of: {allowed}")

        with self._lock:
            binding = self._bindings.get(context_id)
            if binding is None:
                binding = resolver(profile_slot)
                self._bindings[context_id] = binding
            elif binding.profile_slot != profile_slot:
                raise ValueError("An existing context cannot change profile_slot")
            return binding


class ConfiguredResponseRuntime:
    """Resolve production configuration and execute one configured response."""

    def __init__(
        self,
        persona: str = "app",
        profile_loader: Callable[..., dict] = cfg.load_profile,
        knowledge_loader: Callable[..., dict] = cfg.load_knowledge,
        bindings: ContextBindings | None = None,
    ) -> None:
        self.persona = persona
        self.profile_loader = profile_loader
        self.knowledge_loader = knowledge_loader
        self.bindings = bindings or ContextBindings()

    def _resolve(self, profile_slot: str) -> ContextBinding:
        profile = self.profile_loader(profile_slot, "production", self.persona)
        if not profile:
            raise RuntimeError(f"The production {profile_slot} profile is empty.")
        scope = knowledge.settings_from_profile(
            self.knowledge_loader(profile_slot, "production", self.persona)
        )
        return ContextBinding(
            profile_slot=profile_slot,
            profile=dict(profile),
            knowledge_scope=scope,
            revision=_revision(profile, scope),
        )

    def invoke(
        self,
        context_id: str,
        user_message: str,
        profile_slot: str = "baseline",
        grounded: bool = False,
    ) -> dict:
        binding = self.bindings.get_or_create(
            context_id, profile_slot, self._resolve
        )
        if grounded and knowledge.is_enabled(binding.knowledge_scope):
            bundle = run_grounded(
                binding.profile,
                binding.knowledge_scope,
                user_message,
                self.persona,
            )
            result = bundle["result"]
            found = bundle["found"]
        else:
            result = run_variant(binding.profile, user_message)
            found = {
                "documents": [],
                "notes": [SEARCH_DISABLED_NOTE] if grounded else [],
                "index": None,
            }

        return {
            "result": result,
            "found": found,
            "grounded": bool(found["documents"]),
            "profile_slot": binding.profile_slot,
            "configuration_revision": binding.revision,
            "prompt_asset": (
                GROUNDED_ASSET
                if grounded and knowledge.is_enabled(binding.knowledge_scope)
                else binding.profile.get("prompt_asset", "response:v1")
            ),
        }