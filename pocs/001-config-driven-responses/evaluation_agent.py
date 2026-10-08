"""Read-only A2A contract for profile-specific advisory evaluation."""

import asyncio

from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value

from a2a.helpers import new_task_from_user_message, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Part

import evaluation
import rbac


def build_agent_card(base_url):
    return AgentCard(
        name="Advisory Profile Evaluation Agent", version="0.1.0",
        description="Assesses immutable responses under fresh per-profile rules; does not block, rewrite or approve.",
        default_input_modes=[evaluation.REQUEST_MEDIA_TYPE], default_output_modes=[evaluation.RESULT_MEDIA_TYPE],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        supported_interfaces=[AgentInterface(protocol_binding="HTTP+JSON", url=base_url.rstrip("/"), protocol_version="1.0")],
        skills=[AgentSkill(id="advisory-profile-evaluation", name="Evaluate comparison responses",
            description="Returns findings, evidence limitations and used policy revisions.",
            tags=["evaluation", "advisory", "configuration"], input_modes=[evaluation.REQUEST_MEDIA_TYPE],
            output_modes=[evaluation.RESULT_MEDIA_TYPE])],
    )


def parse_request(message):
    if not rbac.evaluation_enabled():
        raise ValueError("Advisory evaluation is not enabled on this runtime.")
    if dict(message.metadata) or message.extensions or len(message.parts) != 1:
        raise ValueError("Supply exactly one structured evaluation request without metadata overrides.")
    part = message.parts[0]
    if part.WhichOneof("content") != "data" or part.media_type != evaluation.REQUEST_MEDIA_TYPE:
        raise ValueError("Unsupported evaluation request media type.")
    return evaluation.validate_request(MessageToDict(part.data))


class EvaluationAgentExecutor(AgentExecutor):
    def __init__(self, runtime=None):
        self.runtime = runtime or evaluation.EvaluationRuntime()

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        if context.message is None:
            raise ValueError("An evaluation message is required.")
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        try:
            payload = parse_request(context.message)
        except (ValueError, TypeError):
            await updater.reject(new_text_message("Invalid or disabled advisory evaluation request."))
            return
        await updater.start_work(new_text_message("Evaluating response wording"))
        try:
            result = await asyncio.wait_for(asyncio.to_thread(self.runtime.evaluate, payload), timeout=75.0)
            result = evaluation.validate_report(result, payload)
        except Exception:
            await updater.failed(new_text_message("Advisory evaluation is unavailable. Generated responses are unchanged."))
            return
        await updater.add_artifact(name="Advisory evaluation", parts=[
            Part(data=ParseDict(result, Value()), media_type=evaluation.RESULT_MEDIA_TYPE),
        ])
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        if context.current_task is not None:
            task = context.current_task
            await TaskUpdater(event_queue, task.id, task.context_id).cancel(new_text_message("Evaluation cancellation requested."))