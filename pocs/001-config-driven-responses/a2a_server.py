"""Local A2A 1.0 server for the configured conversational experience."""

import os

import uvicorn
from hosting import load_environment
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore

from a2a_agent import ExperienceAgentExecutor, build_agent_card
from experience_runtime import ConfiguredResponseRuntime

load_environment()

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9999


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def create_app(
    runtime: ConfiguredResponseRuntime | None = None,
    base_url: str | None = None,
) -> Starlette:
    resolved_url = base_url or os.environ.get(
        "A2A_AGENT_URL", f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    )
    card = build_agent_card(resolved_url)
    handler = DefaultRequestHandler(
        agent_executor=ExperienceAgentExecutor(runtime),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = [Route("/health", health)]
    routes.extend(create_agent_card_routes(card))
    routes.extend(create_rest_routes(handler))
    app = Starlette(routes=routes)
    app.state.agent_card = card
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("A2A_AGENT_HOST", DEFAULT_HOST),
        port=int(os.environ.get("A2A_AGENT_PORT", str(DEFAULT_PORT))),
    )