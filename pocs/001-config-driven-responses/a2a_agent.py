"""A2A contract and executor for the configured response runtime."""

from __future__ import annotations

import asyncio
import logging

from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Value

import config as cfg
import knowledge
from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentSkill,
    Message,
    Part,
)

from experience_runtime import ALLOWED_PROFILE_SLOTS, ConfiguredResponseRuntime

EXPERIENCE_PROFILE_EXTENSION = (
    "https://contoso.example/a2a/extensions/experience-profile/v1"
)
RESULT_MEDIA_TYPE = "application/vnd.contoso.experience-result+json"
MAX_MESSAGE_CHARS = 8_000

_FORBIDDEN_METADATA = frozenset(
    cfg.EDITABLE_KEYS + cfg.COMPARISON_KNOWLEDGE_KEYS + ["store", "label"]
)
_LOG = logging.getLogger(__name__)


def build_agent_card(base_url: str) -> AgentCard:
    skill = AgentSkill(
        id="configured-customer-response",
        name="Configured customer response",
        description=(
            "Answers a customer message using a governed production experience "
            "profile and its configured knowledge scope."
        ),
        tags=["customer-experience", "configuration", "grounding"],
        examples=[
            "Where is my order?",
            "How long do I have to return something?",
        ],
        input_modes=["text/plain"],
        output_modes=["text/plain", RESULT_MEDIA_TYPE],
    )
    extension = AgentExtension(
        uri=EXPERIENCE_PROFILE_EXTENSION,
        description=(
            "Allows an authorized comparison client to select the baseline or "
            "candidate production profile and request configured grounding."
        ),
        required=False,
        params={
            "allowedProfileSlots": sorted(ALLOWED_PROFILE_SLOTS),
            "metadataFields": ["profileSlot", "grounded"],
        },
    )
    return AgentCard(
        name="Configurable Conversational Experience Agent",
        description=(
            "Produces customer-facing responses while keeping prompts, knowledge "
            "filters, and configuration stores behind an opaque A2A boundary."
        ),
        version="0.1.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", RESULT_MEDIA_TYPE],
        capabilities=AgentCapabilities(
            streaming=False,
            push_notifications=False,
            extensions=[extension],
        ),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="HTTP+JSON",
                url=base_url.rstrip("/"),
                protocol_version="1.0",
            )
        ],
        skills=[skill],
    )


def parse_request_options(message: Message) -> tuple[str, str, bool]:
    for part in message.parts:
        if part.WhichOneof("content") != "text":
            raise ValueError("Only text/plain message parts are supported")

    user_message = get_message_text(message).strip()
    if not user_message:
        raise ValueError("A non-empty text message is required")
    if len(user_message) > MAX_MESSAGE_CHARS:
        raise ValueError(f"The message exceeds the {MAX_MESSAGE_CHARS} character limit")

    metadata = dict(message.metadata)
    forbidden = sorted(_FORBIDDEN_METADATA.intersection(metadata))
    if forbidden:
        raise ValueError(
            "Raw configuration metadata is not accepted: " + ", ".join(forbidden)
        )

    uses_extension = EXPERIENCE_PROFILE_EXTENSION in message.extensions
    has_extension_fields = "profileSlot" in metadata or "grounded" in metadata
    if has_extension_fields and not uses_extension:
        raise ValueError("Profile selection requires the declared A2A extension")

    profile_slot = metadata.get("profileSlot", "baseline") if uses_extension else "baseline"
    if not isinstance(profile_slot, str) or profile_slot not in ALLOWED_PROFILE_SLOTS:
        allowed = ", ".join(sorted(ALLOWED_PROFILE_SLOTS))
        raise ValueError(f"profileSlot must be one of: {allowed}")

    grounded = metadata.get("grounded", False) if uses_extension else False
    if not isinstance(grounded, bool):
        raise ValueError("grounded must be a boolean")
    return user_message, profile_slot, grounded


def _result_part(payload: dict) -> Part:
    value = ParseDict(payload, Value())
    return Part(data=value, media_type=RESULT_MEDIA_TYPE)


def _safe_result(bundle: dict) -> dict:
    result = bundle["result"]
    return {
        "profileSlot": bundle["profile_slot"],
        "configurationRevision": bundle["configuration_revision"],
        "promptAsset": bundle["prompt_asset"],
        "finishReason": result.get("finish_reason"),
        "latencySeconds": result.get("latency_s"),
        "promptTokens": result.get("prompt_tokens"),
        "completionTokens": result.get("completion_tokens"),
        "reasoningTokens": result.get("reasoning_tokens"),
        "citations": knowledge.citation_list(bundle["found"]["documents"]),
    }


class ExperienceAgentExecutor(AgentExecutor):
    def __init__(self, runtime: ConfiguredResponseRuntime | None = None) -> None:
        self.runtime = runtime or ConfiguredResponseRuntime()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None:
            raise ValueError("The request does not contain a message")

        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        try:
            user_message, profile_slot, grounded = parse_request_options(context.message)
        except ValueError as exc:
            await updater.reject(new_text_message(str(exc)))
            return

        await updater.start_work(new_text_message("Generating configured response"))
        try:
            bundle = await asyncio.to_thread(
                self.runtime.invoke,
                task.context_id,
                user_message,
                profile_slot,
                grounded,
            )
        except (cfg.AccessDenied, cfg.CredentialError):
            await updater.failed(
                new_text_message("The runtime could not access a required Azure service")
            )
            return
        except ValueError as exc:
            await updater.reject(new_text_message(str(exc)))
            return
        except Exception:
            _LOG.exception("A2A task %s failed", task.id)
            await updater.failed(new_text_message("The configured response failed"))
            return

        await updater.add_artifact(
            name="Configured response",
            parts=[
                new_text_part(bundle["result"]["text"], media_type="text/plain"),
                _result_part(_safe_result(bundle)),
            ],
            extensions=[EXPERIENCE_PROFILE_EXTENSION],
        )
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            return
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.cancel(new_text_message("Cancellation requested"))