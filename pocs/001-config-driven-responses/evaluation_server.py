"""Localhost A2A service for opt-in advisory evaluation."""

import os

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore

import evaluation
from evaluation_agent import EvaluationAgentExecutor, build_agent_card
from hosting import load_environment

load_environment()

MAX_HTTP_BYTES = evaluation.MAX_REQUEST_BYTES * 3 + 16384


class RequestSizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_HTTP_BYTES:
                return await JSONResponse({"error": "Evaluation request is too large."}, status_code=413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


async def health(_request):
    return JSONResponse({"status": "ok"})


def create_app(runtime=None, base_url=None):
    card = build_agent_card(base_url or os.environ.get("A2A_EVALUATOR_URL", "http://127.0.0.1:10000"))
    handler = DefaultRequestHandler(agent_executor=EvaluationAgentExecutor(runtime), task_store=InMemoryTaskStore(), agent_card=card)
    routes = [Route("/health", health)]
    routes.extend(create_agent_card_routes(card))
    routes.extend(create_rest_routes(handler))
    application = Starlette(routes=routes)
    application.add_middleware(RequestSizeLimit)
    return application


app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("A2A_EVALUATOR_PORT", "10000")))