# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.base.build_root import BuildRoot
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import BuildTarget, BuildTargetIdentifier
from pants.bsp.spec.targets import (
    DependencyModule,
    DependencyModulesItem,
    DependencyModulesParams,
    DependencyModulesResult,
    DependencySourcesItem,
    DependencySourcesParams,
    DependencySourcesResult,
    SourceItem,
    SourceItemKind,
    SourcesItem,
    SourcesParams,
    SourcesResult,
    WorkspaceBuildTargetsParams,
    WorkspaceBuildTargetsResult,
)
from pants.build_graph.address import AddressInput
from pants.engine.fs import Workspace
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import _uncacheable_rule, collect_rules, rule
from pants.engine.target import (
    FieldSet,
    SourcesField,
    SourcesPaths,
    SourcesPathsRequest,
    WrappedTarget,
)
from pants.engine.unions import UnionMembership, UnionRule, union


@union
class BSPBuildTargetsRequest:
    """Request language backends to provide BSP `BuildTarget` instances for their managed target
    types."""


@dataclass(frozen=True)
class BSPBuildTargets:
    """Response type for a BSPBuildTargetsRequest."""

    targets: tuple[BuildTarget, ...] = ()
    digest: Digest = EMPTY_DIGEST


# -----------------------------------------------------------------------------------------------
# Workspace Build Targets Request
# See https://build-server-protocol.github.io/docs/specification.html#workspace-build-targets-request
# -----------------------------------------------------------------------------------------------


class WorkspaceBuildTargetsHandlerMapping(BSPHandlerMapping):
    method_name = "workspace/buildTargets"
    request_type = WorkspaceBuildTargetsParams
    response_type = WorkspaceBuildTargetsResult


@_uncacheable_rule
async def bsp_workspace_build_targets(
    _: WorkspaceBuildTargetsParams, union_membership: UnionMembership, workspace: Workspace
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
    output_digest = await Get(Digest, MergeDigests([r.digest for r in responses]))
    workspace.write_digest(output_digest, path_prefix=".pants.d/bsp")
    return WorkspaceBuildTargetsResult(
        targets=tuple(result),
    )


# -----------------------------------------------------------------------------------------------
# Build Target Sources Request
# See https://build-server-protocol.github.io/docs/specification.html#build-target-sources-request
# -----------------------------------------------------------------------------------------------


class BuildTargetSourcesHandlerMapping(BSPHandlerMapping):
    method_name = "buildTarget/sources"
    request_type = SourcesParams
    response_type = SourcesResult


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
    wrapped_target = await Get(WrappedTarget, AddressInput, request.bsp_target_id.address_input)
    target = wrapped_target.target

    if not target.has_field(SourcesField):
        raise AssertionError(
            f"BSP only handles targets with sources: uri={request.bsp_target_id.uri}"
        )

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


# -----------------------------------------------------------------------------------------------
# Dependency Sources Request
# See https://build-server-protocol.github.io/docs/specification.html#dependency-sources-request
# -----------------------------------------------------------------------------------------------


class DependencySourcesHandlerMapping(BSPHandlerMapping):
    method_name = "buildTarget/dependencySources"
    request_type = DependencySourcesParams
    response_type = DependencySourcesResult


@rule
async def bsp_dependency_sources(request: DependencySourcesParams) -> DependencySourcesResult:
    # TODO: This is a stub.
    return DependencySourcesResult(
        tuple(DependencySourcesItem(target=tgt, sources=()) for tgt in request.targets)
    )


# -----------------------------------------------------------------------------------------------
# Dependency Modules Request
# See https://build-server-protocol.github.io/docs/specification.html#dependency-modules-request
# -----------------------------------------------------------------------------------------------


@union
@dataclass(frozen=True)
class BSPDependencyModulesFieldSet(FieldSet):
    """FieldSet used to hook computing dependency modules."""


@dataclass(frozen=True)
class BSPDependencyModules:
    modules: tuple[DependencyModule, ...]
    digest: Digest = EMPTY_DIGEST


class DependencyModulesHandlerMapping(BSPHandlerMapping):
    method_name = "buildTarget/dependencyModules"
    request_type = DependencyModulesParams
    response_type = DependencyModulesResult


@dataclass(frozen=True)
class ResolveOneDependencyModuleRequest:
    bsp_target_id: BuildTargetIdentifier


@dataclass(frozen=True)
class ResolveOneDependencyModuleResult:
    bsp_target_id: BuildTargetIdentifier
    modules: tuple[DependencyModule, ...] = ()
    digest: Digest = EMPTY_DIGEST


@rule
async def resolve_one_dependency_module(
    request: ResolveOneDependencyModuleRequest,
    union_membership: UnionMembership,
) -> ResolveOneDependencyModuleResult:
    wrapped_target = await Get(WrappedTarget, AddressInput, request.bsp_target_id.address_input)
    target = wrapped_target.target

    dep_module_field_sets = union_membership.get(BSPDependencyModulesFieldSet)
    applicable_field_sets = [
        fs.create(target) for fs in dep_module_field_sets if fs.is_applicable(target)
    ]

    if not applicable_field_sets:
        return ResolveOneDependencyModuleResult(bsp_target_id=request.bsp_target_id)

    # TODO: Handle multiple applicable field sets?
    response = await Get(
        BSPDependencyModules, BSPDependencyModulesFieldSet, applicable_field_sets[0]
    )
    return ResolveOneDependencyModuleResult(
        bsp_target_id=request.bsp_target_id,
        modules=response.modules,
        digest=response.digest,
    )


# Note: VSCode expects this endpoint to exist even if the capability bit for it is set `false`.
@_uncacheable_rule
async def bsp_dependency_modules(
    request: DependencyModulesParams, workspace: Workspace
) -> DependencyModulesResult:
    responses = await MultiGet(
        Get(ResolveOneDependencyModuleResult, ResolveOneDependencyModuleRequest(btgt))
        for btgt in request.targets
    )
    output_digest = await Get(Digest, MergeDigests([r.digest for r in responses]))
    workspace.write_digest(output_digest, path_prefix=".pants.d/bsp")
    return DependencyModulesResult(
        tuple(DependencyModulesItem(target=r.bsp_target_id, modules=r.modules) for r in responses)
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(BSPHandlerMapping, WorkspaceBuildTargetsHandlerMapping),
        UnionRule(BSPHandlerMapping, BuildTargetSourcesHandlerMapping),
        UnionRule(BSPHandlerMapping, DependencySourcesHandlerMapping),
        UnionRule(BSPHandlerMapping, DependencyModulesHandlerMapping),
    )
