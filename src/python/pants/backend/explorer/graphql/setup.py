# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from typing import Callable

import strawberry
from starlette.responses import JSONResponse
from strawberry.fastapi import GraphQLRouter

from pants.backend.explorer.browser import Browser
from pants.backend.explorer.graphql.context import GraphQLContext
from pants.backend.explorer.graphql.query.root import Query
from pants.backend.explorer.graphql.subsystem import GraphQLSubsystem
from pants.backend.explorer.server.uvicorn import UvicornServer
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


def graphql_uvicorn_setup(
    browser: Browser,
    graphql: GraphQLSubsystem,
    route: str = "/graphql",
) -> Callable[[UvicornServer], None]:
    def setup(uvicorn: UvicornServer) -> None:
        # Monkey patch, due to limitations in configurability.
        strawberry.fastapi.router.JSONResponse = ExplorerJSONResponse  # type: ignore[attr-defined]

        schema = strawberry.Schema(query=Query)
        graphql_app = GraphQLRouter(
            schema, context_getter=GraphQLContext(uvicorn).create_request_context
        )

        uvicorn.app.include_router(graphql_app, prefix=route)
        if graphql.open_graphiql:
            uvicorn.prerun_tasks.append(
                # Browser.open() needs an unlocked scheduler, so we need to defer that call to a
                # callstack that is not executing a rule.
                lambda: browser.open(uvicorn.request_state, route)
            )

    return setup
