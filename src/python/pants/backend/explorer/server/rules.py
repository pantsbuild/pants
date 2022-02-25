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

from pants.backend.explorer.request_state import RequestState
from pants.backend.explorer.server.query import Query
from pants.backend.explorer.setup import ExplorerServer, ExplorerServerRequest
from pants.backend.project_info.peek import _PeekJsonEncoder
from pants.base.exiter import ExitCode
from pants.engine.rules import collect_rules, rule


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


class UvicornServerRequest(ExplorerServerRequest):
    pass


class UvicornServer:
    def __init__(self, request_state: RequestState):
        self.request_state = request_state

        schema = strawberry.Schema(query=Query)
        graphql_app = GraphQLRouter(schema, context_getter=request_state.context_getter)
        static_files = StaticFiles(directory="src/javascript/explorer/dist", html=True)
        # static_files = StaticFiles(packages=["pants.backend.explorer.server"], html=True)

        app = FastAPI()
        app.include_router(graphql_app, prefix="/graphql")
        app.mount("/", static_files, name="root")

        @app.middleware("http")
        async def default_fallback(request: Request, call_next):
            response = await call_next(request)
            if response.status_code == 404:
                # Our single page app will request a bogus path if reloaded, just serve the app
                # again.
                response = await static_files.get_response("index.html", request.scope)
            return response

        self.app = app
        self.config = Config(
            self.app, callback_notify=self.on_tick, timeout_notify=0.25, log_config=None
        )
        self.server = Server(config=self.config)

    async def on_tick(self) -> None:
        if self.request_state.scheduler_session.is_cancelled:
            print(" => Exiting...")
            self.server.should_exit = True

    def run(self) -> ExitCode:
        print("Starting the Explorer Web UI server...")
        self.server.run()
        return 0


@rule
async def setup_server(request: UvicornServerRequest) -> ExplorerServer:
    return ExplorerServer(main=UvicornServer(request.request_state).run)


def rules():
    return (
        *collect_rules(),
        *ExplorerServerRequest.rules_for_implementation(UvicornServerRequest),
    )
