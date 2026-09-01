"""Synchronous client adapter for the configured response A2A agent."""

from __future__ import annotations

import asyncio
import os

import httpx
from google.protobuf.json_format import MessageToDict

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_message_text, new_text_message
from a2a.types import Role, SendMessageRequest, Task, TaskState

from a2a_agent import EXPERIENCE_PROFILE_EXTENSION, RESULT_MEDIA_TYPE


class A2AClientError(RuntimeError):
    pass


class ConfiguredAgentClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("A2A_AGENT_URL") or "http://127.0.0.1:9999"
        ).rstrip("/")
        self.timeout_s = timeout_s
        self.transport = transport

    async def invoke_async(
        self,
        user_message: str,
        profile_slot: str,
        grounded: bool = False,
        context_id: str | None = None,
    ) -> dict:
        timeout = httpx.Timeout(self.timeout_s)
        async with httpx.AsyncClient(
            timeout=timeout, transport=self.transport
        ) as http_client:
            resolver = A2ACardResolver(http_client, self.base_url)
            card = await resolver.get_agent_card()
            client = await create_client(
                agent=card,
                client_config=ClientConfig(
                    streaming=False,
                    httpx_client=http_client,
                    supported_protocol_bindings=["HTTP+JSON"],
                ),
            )
            message = new_text_message(
                user_message,
                context_id=context_id,
                role=Role.ROLE_USER,
            )
            message.extensions.append(EXPERIENCE_PROFILE_EXTENSION)
            message.metadata.update(
                {"profileSlot": profile_slot, "grounded": grounded}
            )
            request = SendMessageRequest(message=message)

            task = None
            try:
                async for event in client.send_message(request):
                    candidate = event[0] if isinstance(event, tuple) else event
                    if isinstance(candidate, Task):
                        task = candidate
                    elif (
                        hasattr(candidate, "WhichOneof")
                        and candidate.WhichOneof("payload") == "task"
                    ):
                        task = candidate.task
            finally:
                await client.close()

        if task is None:
            raise A2AClientError("The agent did not return an A2A task")
        if task.status.state != TaskState.TASK_STATE_COMPLETED:
            detail = (
                get_message_text(task.status.message)
                if task.status.HasField("message")
                else "No status detail was returned"
            )
            raise A2AClientError(f"A2A task did not complete: {detail}")

        answer = ""
        provenance = {}
        for artifact in task.artifacts:
            for part in artifact.parts:
                content_kind = part.WhichOneof("content")
                if content_kind == "text" and part.media_type in ("", "text/plain"):
                    answer = part.text
                elif content_kind == "data" and part.media_type == RESULT_MEDIA_TYPE:
                    provenance = MessageToDict(part.data)

        if not answer:
            raise A2AClientError("The completed task did not contain a text artifact")

        return {
            "task_id": task.id,
            "context_id": task.context_id,
            "profile_slot": provenance.get("profileSlot", profile_slot),
            "configuration_revision": provenance.get("configurationRevision"),
            "prompt_asset": provenance.get("promptAsset"),
            "citations": provenance.get("citations", []),
            "result": {
                "text": answer,
                "messages": [],
                "latency_s": provenance.get("latencySeconds"),
                "finish_reason": provenance.get("finishReason"),
                "prompt_tokens": provenance.get("promptTokens"),
                "completion_tokens": provenance.get("completionTokens"),
                "reasoning_tokens": provenance.get("reasoningTokens"),
            },
        }

    def invoke(
        self,
        user_message: str,
        profile_slot: str,
        grounded: bool = False,
        context_id: str | None = None,
    ) -> dict:
        try:
            return asyncio.run(
                self.invoke_async(user_message, profile_slot, grounded, context_id)
            )
        except A2AClientError:
            raise
        except Exception as exc:
            raise A2AClientError(f"Could not call {self.base_url}: {exc}") from exc