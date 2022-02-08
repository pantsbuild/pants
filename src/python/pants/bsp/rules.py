# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.bsp.spec import (
    BuildServerCapabilities,
    BuildTarget,
    InitializeBuildParams,
    InitializeBuildResult,
    WorkspaceBuildTargetsParams,
    WorkspaceBuildTargetsResult,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import QueryRule, collect_rules, rule
from pants.engine.unions import UnionMembership, union
from pants.version import VERSION


@union
class BSPBuildTargetsRequest:
    """Request language backends to provide BSP `BuildTarget` instances for their managed target
    types."""


@dataclass(frozen=True)
class BSPBuildTargets:
    targets: tuple[BuildTarget, ...]


@rule
async def bsp_build_initialize(_request: InitializeBuildParams) -> InitializeBuildResult:
    return InitializeBuildResult(
        display_name="Pants",
        version=VERSION,
        bsp_version="0.0.1",  # TODO: replace with an actual BSP version
        capabilities=BuildServerCapabilities(
            compile_provider=None,
            test_provider=None,
            run_provider=None,
            debug_provider=None,
            inverse_sources_provider=None,
            dependency_sources_provider=None,
            dependency_modules_provider=None,
            resources_provider=None,
            can_reload=None,
            build_target_changed_provider=None,
        ),
        data=None,
    )


@rule
async def bsp_workspace_build_targets(
    _: WorkspaceBuildTargetsParams, union_membership: UnionMembership
) -> WorkspaceBuildTargetsResult:
    request_types = union_membership.get(BSPBuildTargetsRequest)
    responses = await MultiGet(
        Get(BSPBuildTargets, BSPBuildTargetsRequest, request_type())
        for request_type in request_types
    )
    result: list[BuildTarget] = []
    for response in responses:
        result.extend(response.targets)
    result.sort(key=lambda btgt: btgt.id.uri)
    return WorkspaceBuildTargetsResult(
        targets=tuple(result),
    )


def rules():
    return (
        *collect_rules(),
        QueryRule(InitializeBuildResult, (InitializeBuildParams,)),
        QueryRule(WorkspaceBuildTargetsResult, (WorkspaceBuildTargetsParams,)),
    )
