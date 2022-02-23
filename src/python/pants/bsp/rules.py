# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.base.build_root import BuildRoot
from pants.bsp.spec import (
    BuildServerCapabilities,
    BuildTarget,
    BuildTargetIdentifier,
    InitializeBuildParams,
    InitializeBuildResult,
    SourceItem,
    SourceItemKind,
    SourcesItem,
    SourcesParams,
    SourcesResult,
    WorkspaceBuildTargetsParams,
    WorkspaceBuildTargetsResult,
)
from pants.build_graph.address import AddressInput
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import QueryRule, collect_rules, rule
from pants.engine.target import SourcesField, SourcesPaths, SourcesPathsRequest, WrappedTarget
from pants.engine.unions import UnionMembership, union
from pants.version import VERSION

BSP_VERSION = "2.0.0"


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
        bsp_version=BSP_VERSION,  # TODO: replace with an actual BSP version
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


# -----------------------------------------------------------------------------------------------
# Workspace Build Targets Request
# See https://build-server-protocol.github.io/docs/specification.html#workspace-build-targets-request
# -----------------------------------------------------------------------------------------------


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


# -----------------------------------------------------------------------------------------------
# Build Target Sources Request
# See https://build-server-protocol.github.io/docs/specification.html#build-target-sources-request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MaterializeBuildTargetSourcesRequest:
    bsp_target_id: BuildTargetIdentifier


@dataclass(frozen=True)
class MaterializeBuildTargetSourcesResult:
    sources_item: SourcesItem


@rule
async def materialize_bsp_build_target_sources(
    request: MaterializeBuildTargetSourcesRequest,
    build_root: BuildRoot,
) -> MaterializeBuildTargetSourcesResult:
    uri = request.bsp_target_id.uri
    if not uri.startswith("pants:"):
        raise ValueError(f"Unknown URI for Pants BSP: {uri}")
    raw_addr = uri[len("pants:") :]

    wrapped_target = await Get(WrappedTarget, AddressInput, AddressInput.parse(raw_addr))
    target = wrapped_target.target

    if not target.has_field(SourcesField):
        raise AssertionError(f"BSP only handles targets with sources: uri={uri}")

    sources_paths = await Get(SourcesPaths, SourcesPathsRequest(target[SourcesField]))
    sources_full_paths = [
        build_root.pathlib_path.joinpath(src_path) for src_path in sources_paths.files
    ]

    sources_item = SourcesItem(
        target=request.bsp_target_id,
        sources=tuple(
            SourceItem(
                uri=src_full_path.as_uri(),
                kind=SourceItemKind.FILE,
                generated=False,
            )
            for src_full_path in sources_full_paths
        ),
        roots=(),
    )

    return MaterializeBuildTargetSourcesResult(sources_item)


@rule
async def bsp_build_target_sources(request: SourcesParams) -> SourcesResult:
    sources_items = await MultiGet(
        Get(MaterializeBuildTargetSourcesResult, MaterializeBuildTargetSourcesRequest(btgt))
        for btgt in request.targets
    )
    return SourcesResult(items=tuple(si.sources_item for si in sources_items))


def rules():
    return (
        *collect_rules(),
        QueryRule(InitializeBuildResult, (InitializeBuildParams,)),
        QueryRule(WorkspaceBuildTargetsResult, (WorkspaceBuildTargetsParams,)),
        QueryRule(SourcesResult, (SourcesParams,)),
    )
