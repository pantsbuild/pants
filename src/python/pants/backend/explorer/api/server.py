# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import strawberry
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from strawberry.fastapi import GraphQLRouter
from uvicorn import Config, Server  # type: ignore

from pants.backend.explorer.api.query import Query
from pants.backend.explorer.request_state import RequestState


def create_app(request_state: RequestState):
    schema = strawberry.Schema(query=Query)
    graphql_app = GraphQLRouter(schema, context_getter=request_state.context_getter)

    app = FastAPI()
    app.include_router(graphql_app, prefix="/graphql")
    app.mount("/", StaticFiles(directory="src/javascript/explorer/dist", html=True), name="root")

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
