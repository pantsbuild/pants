# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os.path
from collections import defaultdict
from dataclasses import dataclass
from typing import ClassVar, Generic, Sequence, Type, TypeVar

from pants.base.build_root import BuildRoot
from pants.base.specs import AddressSpecs, Specs
from pants.base.specs_parser import SpecsParser
from pants.bsp.goal import BSPGoal
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import BSPData, BuildTarget, BuildTargetCapabilities, BuildTargetIdentifier
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
from pants.source.source_root import SourceRootsRequest, SourceRootsResult
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

_logger = logging.getLogger(__name__)

_FS = TypeVar("_FS", bound=FieldSet)


@union
@dataclass(frozen=True)
class BSPBuildTargetsMetadataRequest(Generic[_FS]):
    """Hook to allow language backends to provide metadata for BSP build targets."""

    language_id: ClassVar[str]
    can_merge_metadata_from: ClassVar[tuple[str, ...]]
    field_set_type: ClassVar[Type[_FS]]

    field_sets: tuple[_FS, ...]


@dataclass(frozen=True)
class BSPBuildTargetsMetadataResult:
    """Response type for a BSPBuildTargetsMetadataRequest."""

    # Metadata for the `data` field of the final `BuildTarget`.
    metadata: BSPData | None = None

    # Build capabilities
    can_compile: bool = False
    can_test: bool = False
    can_run: bool = False
    can_debug: bool = False

    # Output to write into `.pants.d/bsp` for access by IDE.
    digest: Digest = EMPTY_DIGEST


@dataclass(frozen=True)
class BSPBuildTargetInternal:
    name: str
    specs: Specs


@dataclass(frozen=True)
class BSPBuildTargetsNew:
    targets_mapping: FrozenDict[str, BSPBuildTargetInternal]


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
        Get(Specs, _ParseOneBSPMappingRequest(tuple(value)))
        for value in bsp_goal.target_mapping.values()
    )
    addr_specs = {
        key: BSPBuildTargetInternal(key, specs_for_key)
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


@dataclass(frozen=True)
class GenerateOneBSPBuildTargetRequest:
    bsp_target: BSPBuildTargetInternal


@dataclass(frozen=True)
class GenerateOneBSPBuildTargetResult:
    build_target: BuildTarget
    digest: Digest = EMPTY_DIGEST


def find_metadata_merge_order(
    metadata_request_types: Sequence[Type[BSPBuildTargetsMetadataRequest]],
) -> Sequence[Type[BSPBuildTargetsMetadataRequest]]:
    if len(metadata_request_types) <= 1:
        return metadata_request_types

    # Naive algorithm (since we only support Java and Scala backends), find the metadata request type that cannot
    # merge from another and put that first.
    if len(metadata_request_types) != 2:
        raise AssertionError(
            "BSP core rules only support naive ordering of language-backend metadata. Contact Pants developers."
        )
    if not metadata_request_types[0].can_merge_metadata_from:
        return metadata_request_types
    elif not metadata_request_types[1].can_merge_metadata_from:
        return list(reversed(metadata_request_types))
    else:
        raise AssertionError(
            "BSP core rules only support naive ordering of language-backend metadata. Contact Pants developers."
        )


@rule
async def generate_one_bsp_build_target_request(
    request: GenerateOneBSPBuildTargetRequest,
    union_membership: UnionMembership,
    build_root: BuildRoot,
) -> GenerateOneBSPBuildTargetResult:
    # Find all Pants targets that are part of this BSP build target.
    targets = await Get(Targets, AddressSpecs, request.bsp_target.specs.address_specs)

    # Classify the targets by the language backends that claim them to provide metadata for them.
    field_sets_by_lang_id: dict[str, OrderedSet[FieldSet]] = defaultdict(OrderedSet)
    # lang_ids_by_field_set: dict[Type[FieldSet], set[str]] = defaultdict(set)
    metadata_request_types: FrozenOrderedSet[
        Type[BSPBuildTargetsMetadataRequest]
    ] = union_membership.get(BSPBuildTargetsMetadataRequest)
    metadata_request_types_by_lang_id = {
        metadata_request_type.language_id: metadata_request_type
        for metadata_request_type in metadata_request_types
    }
    for tgt in targets:
        for metadata_request_type in metadata_request_types:
            field_set_type: Type[FieldSet] = metadata_request_type.field_set_type
            if field_set_type.is_applicable(tgt):
                field_sets_by_lang_id[metadata_request_type.language_id].add(
                    field_set_type.create(tgt)
                )
                # lang_ids_by_field_set[field_set_type].add(metadata_request_type.language_id)

    # TODO: Consider how to check whether the provided languages are compatible or whether compatible resolves
    # selected.

    # Request each language backend to provide metadata for the BuildTarget.
    metadata_results = await MultiGet(
        Get(
            BSPBuildTargetsMetadataResult,
            BSPBuildTargetsMetadataRequest,
            metadata_request_types_by_lang_id[lang_id](field_sets=tuple(field_sets)),
        )
        for lang_id, field_sets in field_sets_by_lang_id.items()
    )
    metadata_results_by_lang_id = {
        lang_id: metadata_result
        for lang_id, metadata_result in zip(field_sets_by_lang_id.keys(), metadata_results)
    }

    # Pretend to merge the metadata into a single piece of metadata, but really just choose the metadata
    # from the last provider.
    metadata_merge_order = find_metadata_merge_order(
        [metadata_request_types_by_lang_id[lang_id] for lang_id in field_sets_by_lang_id.keys()]
    )
    # TODO: None if no metadata obtained.
    metadata = metadata_results_by_lang_id[metadata_merge_order[-1].language_id].metadata
    digest = await Get(Digest, MergeDigests([r.digest for r in metadata_results]))

    # Determine base directory for this build target.
    # TODO: Use a source root?
    targets_with_sources = [tgt for tgt in targets if tgt.has_field(SourcesField)]
    sources_paths = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(tgt[SourcesField])) for tgt in targets_with_sources
    )
    _logger.info(f"sources_paths = {sources_paths}")
    merged_source_files: set[str] = set()
    for sp in sources_paths:
        merged_source_files.update(sp.files)

    source_roots_result = await Get(SourceRootsResult, SourceRootsRequest, SourceRootsRequest.for_files(merged_source_files))
    source_root_paths = {x.path for x in source_roots_result.path_to_root.values()}
    if len(source_root_paths) == 0:
        base_dir = build_root.pathlib_path
    elif len(source_root_paths) == 1:
        base_dir = build_root.pathlib_path.joinpath(list(source_root_paths)[0])
    else:
        raise ValueError("Multiple source roots not supported for BSP build target.")

    # base_dir = build_root.pathlib_path
    # if merged_sources_dirs:
    #     _logger.info(f"merged_sources_dirs = {merged_sources_dirs}")
    #     common_path = os.path.commonpath(list(merged_sources_dirs))
    #     _logger.info(f"common_path = {common_path}")
    #     if common_path:
    #         base_dir = base_dir.joinpath(common_path)
    # _logger.info(f"base_dir = {base_dir}")

    return GenerateOneBSPBuildTargetResult(
        build_target=BuildTarget(
            id=BuildTargetIdentifier(f"pants:{request.bsp_target.name}"),
            display_name=request.bsp_target.name,
            base_directory=base_dir.as_uri(),
            tags=(),
            capabilities=BuildTargetCapabilities(
                can_compile=any(r.can_compile for r in metadata_results),
                can_test=any(r.can_test for r in metadata_results),
                can_run=any(r.can_run for r in metadata_results),
                can_debug=any(r.can_debug for r in metadata_results),
            ),
            language_ids=tuple(sorted(field_sets_by_lang_id.keys())),
            dependencies=(),
            data=metadata,
        ),
        digest=digest,
    )


@_uncacheable_rule
async def bsp_workspace_build_targets(
    _: WorkspaceBuildTargetsParams,
    bsp_build_targets: BSPBuildTargetsNew,
    workspace: Workspace,
) -> WorkspaceBuildTargetsResult:
    bsp_target_results = await MultiGet(
        Get(GenerateOneBSPBuildTargetResult, GenerateOneBSPBuildTargetRequest(target_internal))
        for target_internal in bsp_build_targets.targets_mapping.values()
    )
    digest = await Get(Digest, MergeDigests([r.digest for r in bsp_target_results]))
    if digest != EMPTY_DIGEST:
        workspace.write_digest(digest, path_prefix=".pants.d/bsp")

    return WorkspaceBuildTargetsResult(
        targets=tuple(r.build_target for r in bsp_target_results),
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
        Targets,
        AddressSpecs,
        bsp_build_targets.targets_mapping[bsp_target_name].specs.address_specs,
    )
    targets_with_sources = [tgt for tgt in targets if tgt.has_field(SourcesField)]

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
