# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import strawberry
import uvicorn  # type: ignore
from fastapi import FastAPI
from strawberry.fastapi import GraphQLRouter

from pants.backend.explorer.api.query import Query
from pants.backend.explorer.request_state import RequestState


def create_app(request_state: RequestState):
    schema = strawberry.Schema(query=Query)
    graphql_app = GraphQLRouter(schema, context_getter=request_state.context_getter)
    app = FastAPI()
    app.include_router(graphql_app, prefix="/graphql")
    return app


def run(request_state: RequestState):
    print("Starting the Explorer Web UI server...")
    app = create_app(request_state)
    uvicorn.run(app)
