# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json

import strawberry
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse
from strawberry.fastapi import GraphQLRouter
from uvicorn import Config, Server  # type: ignore

from pants.backend.explorer.api.query import Query
from pants.backend.explorer.request_state import RequestState
from pants.backend.project_info.peek import _PeekJsonEncoder


class ExplorerJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            cls=_PeekJsonEncoder,
        ).encode("utf-8")


# Monkey patch, due to limitations in configurability.
strawberry.fastapi.router.JSONResponse = ExplorerJSONResponse  # type: ignore[attr-defined]


def create_app(request_state: RequestState):
    schema = strawberry.Schema(query=Query)
    graphql_app = GraphQLRouter(schema, context_getter=request_state.context_getter)
    static_files = StaticFiles(directory="src/javascript/explorer/dist", html=True)

    app = FastAPI()
    app.include_router(graphql_app, prefix="/graphql")
    app.mount("/", static_files, name="root")

    @app.middleware("http")
    async def default_fallback(request: Request, call_next):
        response = await call_next(request)
        if response.status_code == 404:
            response = await static_files.get_response("index.html", request.scope)
        return response

    return app


def run(request_state: RequestState):
    print("Starting the Explorer Web UI server...")
    server: Server | None = None

    async def on_tick() -> None:
        nonlocal server
        if server and request_state.scheduler_session.is_cancelled:
            print(" => Exiting...")
            server.should_exit = True

    app = create_app(request_state)
    config = Config(app, callback_notify=on_tick, timeout_notify=0.25, log_config=None)
    server = Server(config=config)
    server.run()
