"""Streamlit-facing synchronous adapter for the advisory A2A evaluator."""

import asyncio
import os

import httpx
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import Part, Role, SendMessageRequest, Task, TaskState

import evaluation


class EvaluationClientError(RuntimeError):
    pass


class EvaluationClient:
    def __init__(self, base_url=None, timeout_s=90.0, transport=None):
        self.base_url = (base_url or os.environ.get("A2A_EVALUATOR_URL") or "http://127.0.0.1:10000").rstrip("/")
        self.timeout_s = timeout_s
        self.transport = transport

    async def evaluate_async(self, payload):
        request = evaluation.validate_request(payload)
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_s), transport=self.transport) as http_client:
            card = await A2ACardResolver(http_client, self.base_url).get_agent_card()
            client = await create_client(agent=card, client_config=ClientConfig(
                streaming=False, httpx_client=http_client, supported_protocol_bindings=["HTTP+JSON"],
            ))
            message = new_text_message("", role=Role.ROLE_USER)
            message.parts.clear()
            message.parts.append(Part(data=ParseDict(request, Value()), media_type=evaluation.REQUEST_MEDIA_TYPE))
            task = None
            try:
                async for event in client.send_message(SendMessageRequest(message=message)):
                    candidate = event[0] if isinstance(event, tuple) else event
                    if isinstance(candidate, Task):
                        task = candidate
                    elif hasattr(candidate, "WhichOneof") and candidate.WhichOneof("payload") == "task":
                        task = candidate.task
            finally:
                await client.close()
        if task is None or task.status.state != TaskState.TASK_STATE_COMPLETED:
            raise EvaluationClientError("Advisory evaluation did not complete. Generated responses are unchanged.")
        results = [MessageToDict(part.data) for artifact in task.artifacts for part in artifact.parts
                   if part.WhichOneof("content") == "data" and part.media_type == evaluation.RESULT_MEDIA_TYPE]
        if len(results) != 1:
            raise EvaluationClientError("The evaluator did not return one complete advisory report.")
        return evaluation.validate_report(results[0], request)

    def evaluate(self, payload):
        try:
            return asyncio.run(self.evaluate_async(payload))
        except EvaluationClientError:
            raise
        except Exception:
            raise EvaluationClientError("The advisory evaluator is unavailable or returned an invalid report. Generated responses are unchanged.") from None