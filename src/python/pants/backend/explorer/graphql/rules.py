# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.explorer.graphql.setup import graphql_uvicorn_setup
from pants.backend.explorer.server.uvicorn import UvicornServerSetup, UvicornServerSetupRequest
from pants.backend.project_info.peek import TargetDatas
from pants.base.specs import Specs
from pants.engine.rules import QueryRule, collect_rules, rule
from pants.engine.target import AllTargets, AllUnexpandedTargets, Targets, UnexpandedTargets
from pants.engine.unions import UnionRule


class GraphQLUvicornServerSetupRequest(UvicornServerSetupRequest):
    pass


@rule
async def get_graphql_uvicorn_setup(
    request: GraphQLUvicornServerSetupRequest,
) -> UvicornServerSetup:
    return UvicornServerSetup(graphql_uvicorn_setup)


def rules():
    return (
        *collect_rules(),
        UnionRule(UvicornServerSetupRequest, GraphQLUvicornServerSetupRequest),
        # Root query data rules for graphql.
        QueryRule(AllTargets, ()),
        QueryRule(AllUnexpandedTargets, ()),
        QueryRule(TargetDatas, (UnexpandedTargets,)),
        QueryRule(Targets, (Specs,)),
    )
