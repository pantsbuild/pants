# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import strawberry
import uvicorn  # type: ignore
from fastapi import FastAPI, Request
from strawberry.fastapi import GraphQLRouter
from strawberry.types import Info

from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.rules import TaskRule


@dataclass(frozen=True)
class RequestState:
    build_configuration: BuildConfiguration
    scheduler_session: SchedulerSession


@strawberry.type
class User:
    name: str
    age: int


@strawberry.type
class RuleInfo:
    names: List[str]


@strawberry.type
class Query:
    @strawberry.field
    def user(self, info: Info) -> User:
        return User(name=info.context["request"].state.name, age=10)

    @strawberry.field
    def rules(self, info: Info) -> RuleInfo:
        request_state: RequestState = info.context["request"].state.pants
        return RuleInfo(
            names=sorted(
                rule.canonical_name
                for rule in request_state.build_configuration.rule_to_providers.keys()
                if isinstance(rule, TaskRule)
            )
        )


schema = strawberry.Schema(query=Query)
graphql_app = GraphQLRouter(schema)


def create_app(request_state: RequestState):
    app = FastAPI()
    app.include_router(graphql_app, prefix="/graphql")

    @app.middleware("http")
    async def explorer_state(request: Request, call_next):
        request.state.name = "Dora Explorer"
        request.state.pants = request_state
        response = await call_next(request)
        return response

    return app


def run(request_state: RequestState):
    app = create_app(request_state)

    uvicorn.run(app)
