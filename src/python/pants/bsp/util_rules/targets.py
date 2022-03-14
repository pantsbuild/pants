# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os.path
from dataclasses import dataclass
from typing import ClassVar

from pants.base.build_root import BuildRoot
from pants.base.specs import AddressSpecs, Specs
from pants.base.specs_parser import SpecsParser
from pants.bsp.goal import BSPGoal
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import BuildTarget, BuildTargetCapabilities, BuildTargetIdentifier
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
    Targets,
    WrappedTarget,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.frozendict import FrozenDict


_logger = logging.getLogger(__name__)


@union
@dataclass(frozen=True)
class BSPBuildTargetsFieldSet:
    language_id: ClassVar[str]


@dataclass(frozen=True)
class BSPBuildTargetsNew:
    targets_mapping: FrozenDict[str, Specs]


@dataclass(frozen=True)
class BSPBuildTargets:
    """Response type for a BSPBuildTargetsRequest."""

    targets: tuple[BuildTarget, ...] = ()
    digest: Digest = EMPTY_DIGEST


@dataclass(frozen=True)
class _ParseOneBSPMappingRequest:
    raw_specs: tuple[str, ...]


@rule
async def parse_one_bsp_mapping(request: _ParseOneBSPMappingRequest) -> Specs:
    specs_parser = SpecsParser()
    specs = specs_parser.parse_specs(request.raw_specs)
    return specs


@rule
async def materialize_bsp_build_targets(bsp_goal: BSPGoal) -> BSPBuildTargetsNew:
    specs_for_keys = await MultiGet(
        Get(Specs, _ParseOneBSPMappingRequest(tuple(value))) for value in bsp_goal.target_mapping.values()
    )
    addr_specs = {
        key: specs_for_key
        for key, specs_for_key in zip(bsp_goal.target_mapping.keys(), specs_for_keys)
    }
    return BSPBuildTargetsNew(FrozenDict(addr_specs))


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
    _: WorkspaceBuildTargetsParams,
    bsp_build_targets: BSPBuildTargetsNew,
    union_membership: UnionMembership,
    workspace: Workspace,
    build_root: BuildRoot,
) -> WorkspaceBuildTargetsResult:
    # metadata_field_set_types = union_membership.get(BSPBuildTargetsFieldSet)

    result: list[BuildTarget] = []
    for bsp_target_name, specs in bsp_build_targets.targets_mapping.items():
        targets = await Get(Targets, AddressSpecs, specs.address_specs)
        targets_with_sources = [tgt for tgt in targets if tgt.has_field(SourcesField)]
        # TODO:  What about literal specs?

        # applicable_field_sets: dict[Target, list[Type[BSPBuildTargetsFieldSet]]] = defaultdict(list)
        # for tgt in targets:
        #     for field_set_type in metadata_field_set_types:
        #         if field_set_type.is_applicable(tgt):
        #             applicable_field_sets[tgt].append(field_set_type)

        sources_paths = await MultiGet(
            Get(SourcesPaths, SourcesPathsRequest(tgt[SourcesField])) for tgt in targets_with_sources
        )
        merged_sources_dirs: set[str] = set()
        for sp in sources_paths:
            merged_sources_dirs.update(sp.dirs)

        base_dir = build_root.pathlib_path
        if merged_sources_dirs:
            common_path = os.path.commonpath(list(merged_sources_dirs))
            if common_path:
                base_dir = base_dir.joinpath(common_path)

        result.append(
            BuildTarget(
                id=BuildTargetIdentifier(f"pants:{bsp_target_name}"),
                display_name=bsp_target_name,
                base_directory=base_dir.as_uri(),
                tags=(),
                capabilities=BuildTargetCapabilities(
                    can_compile=True,
                ),
                language_ids=("java", "scala"),
                dependencies=(),
                data_kind=None,
                data=None,
            )
        )
    # responses = await MultiGet(
    #     Get(BSPBuildTargets, BSPBuildTargetsFieldSet, request_type())
    #     for request_type in request_types
    # )
    # for response in responses:
    #     result.extend(response.targets)
    # result.sort(key=lambda btgt: btgt.id.uri)
    # output_digest = await Get(Digest, MergeDigests([r.digest for r in responses]))
    # workspace.write_digest(output_digest, path_prefix=".pants.d/bsp")

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
    bsp_build_targets: BSPBuildTargetsNew,
) -> MaterializeBuildTargetSourcesResult:
    bsp_target_name = request.bsp_target_id.uri[len("pants:") :]
    if bsp_target_name not in bsp_build_targets.targets_mapping:
        raise ValueError(f"Invalid BSP target name: {request.bsp_target_id}")
    targets = await Get(
        Targets, AddressSpecs, bsp_build_targets.targets_mapping[bsp_target_name].address_specs
    )
    targets_with_sources = [tgt for tgt in targets if tgt.has_field(SourcesField)]

    # wrapped_target = await Get(WrappedTarget, AddressInput, request.bsp_target_id.address_input)
    # target = wrapped_target.target
    #
    # if not target.has_field(SourcesField):
    #     raise AssertionError(
    #         f"BSP only handles targets with sources: uri={request.bsp_target_id.uri}"
    #     )
    #
    # sources_paths = await Get(SourcesPaths, SourcesPathsRequest(target[SourcesField]))
    # sources_full_paths = [
    #     build_root.pathlib_path.joinpath(src_path) for src_path in sources_paths.files
    # ]

    sources_paths = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(tgt[SourcesField])) for tgt in targets_with_sources
    )
    merged_sources_dirs: set[str] = set()
    merged_sources_files: set[str] = set()
    for sp in sources_paths:
        merged_sources_dirs.update(sp.dirs)
        merged_sources_files.update(sp.files)
    _logger.info(f"merged_sources_dirs={merged_sources_dirs}")
    _logger.info(f"merged_sources_files={merged_sources_files}")

    base_dir = build_root.pathlib_path
    if merged_sources_dirs:
        common_path = os.path.commonpath(list(merged_sources_dirs))
        if common_path:
            base_dir = base_dir.joinpath(common_path)

    sources_item = SourcesItem(
        target=request.bsp_target_id,
        sources=tuple(
            SourceItem(
                uri=build_root.pathlib_path.joinpath(filename).as_uri(),
                kind=SourceItemKind.FILE,
                generated=False,
            )
            for filename in sorted(merged_sources_files)
        ),
        roots=(base_dir.as_uri(),),
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
