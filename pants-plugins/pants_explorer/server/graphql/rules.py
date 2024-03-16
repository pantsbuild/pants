# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants_explorer.server.browser import Browser, BrowserRequest
from pants_explorer.server.graphql.setup import graphql_uvicorn_setup
from pants_explorer.server.graphql.subsystem import GraphQLSubsystem
from pants_explorer.server.uvicorn import UvicornServerSetup, UvicornServerSetupRequest

from pants.backend.project_info.peek import TargetDatas
from pants.base.specs import Specs
from pants.engine.environment import EnvironmentName
from pants.engine.rules import Get, QueryRule, collect_rules, rule
from pants.engine.target import AllUnexpandedTargets, UnexpandedTargets
from pants.engine.unions import UnionRule


class GraphQLUvicornServerSetupRequest(UvicornServerSetupRequest):
    pass


@rule
async def get_graphql_uvicorn_setup(
    request: GraphQLUvicornServerSetupRequest, graphql: GraphQLSubsystem
) -> UvicornServerSetup:
    browser = await Get(Browser, BrowserRequest, request.browser_request())
    return UvicornServerSetup(graphql_uvicorn_setup(browser, graphql=graphql))


def rules():
    return (
        *collect_rules(),
        UnionRule(UvicornServerSetupRequest, GraphQLUvicornServerSetupRequest),
        # Root query data rules for graphql.
        QueryRule(AllUnexpandedTargets, (EnvironmentName,)),
        QueryRule(TargetDatas, (UnexpandedTargets, EnvironmentName)),
        QueryRule(UnexpandedTargets, (Specs, EnvironmentName)),
    )
