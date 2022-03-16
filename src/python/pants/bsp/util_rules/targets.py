# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import functools
import logging
import os.path
from collections import defaultdict
from dataclasses import dataclass
from typing import ClassVar, TypeVar

from pants.backend.scala.bsp.util_rules import ScalaBuildTargetInfo
from pants.base.build_root import BuildRoot
from pants.base.specs import AddressSpecs, Specs
from pants.base.specs_parser import SpecsParser
from pants.bsp.goal import BSPGoal
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import BuildTarget, BuildTargetCapabilities, BuildTargetIdentifier, BSPData
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
    WrappedTarget, Target,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.jvm.target_types import JvmResolveField
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import OrderedSet

_logger = logging.getLogger(__name__)

_FS = TypeVar("_FS", bound=FieldSet)


@union
@dataclass(frozen=True)
class BSPBuildTargetsMetadataRequest:
    """Hook to allow language backends to provide metadata for BSP build targets."""
    language_id: ClassVar[str]
    compatible_language_ids: ClassVar[tuple[str, ...]]
    field_set_type: ClassVar[type[_FS]]

    field_sets: tuple[_FS, ...]


class BSPBuildTargetMetadata(BSPData):
    # Merge this `BuildTargetMetadata` with a `BuildTargetMetadata` from same or compatible language backend.
    def merge(self, other: BSPBuildTargetMetadata) -> BSPBuildTargetMetadata:
        raise NotImplementedError


@dataclass(frozen=True)
class BSPBuildTargetsMetadataResult:
    """Response type for a BSPBuildTargetsMetadataRequest."""

    # Metadata for the `data` field of the final `BuildTarget`.
    metadata: BSPBuildTargetMetadata

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


@dataclass(frozen=True)
class GenerateOneBSPBuildTargetRequest:
    bsp_target: BSPBuildTargetInternal


@dataclass(frozen=True)
class GenerateOneBSPBuildTargetResult:
    build_target: BuildTarget
    digest: Digest = EMPTY_DIGEST


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
    lang_ids_by_field_set: dict[FieldSet, set[str]] = defaultdict(set)
    metadata_request_types = union_membership.get(BSPBuildTargetsMetadataRequest)
    metadata_request_types_by_lang_id = {metadata_request_type.language_id: metadata_request_type for metadata_request_type in metadata_request_types}
    for tgt in targets:
        for metadata_request_type in metadata_request_types:
            if metadata_request_type.field_set_type.is_applicable(tgt):
                field_sets_by_lang_id[metadata_request_type.language_id].add(metadata_request_type.field_set_type.create(tgt))
                lang_ids_by_field_set[tgt].add(metadata_request_type.language_id)

    # Ensure that metadata is being provided only by languages compatible with each other. This guarantees metadata
    # can be merged to produce the final metadata for this BSP build target.
    for current_lang_id in lang_ids_by_field_set.keys():
        for other_lang_id, other_lang in metadata_request_types_by_lang_id.items():
            if current_lang_id == other_lang_id:
                continue
            if current_lang_id not in other_lang.compatible_language_ids:
                raise ValueError(
                    f"BSP build target `{request.bsp_target.name}` resolves to an incompatible set of languages. "
                    f"Language `{current_lang_id}` is not compatible with `{other_lang_id}`."
                )

    # TODO: Provide a way to ensure that other compatibility criteria met. For example, JVM resolve.

    # Request each language backend to provide metadata.
    metadata_results = await MultiGet(
        Get(
            BSPBuildTargetsMetadataResult,
            BSPBuildTargetsMetadataRequest,
            metadata_request_types_by_lang_id[lang_id](
                field_sets=tuple(field_sets)
            )
        )
        for lang_id, field_sets in field_sets_by_lang_id.items()
    )

    # Merge the metadata into a single piece of metadata.
    metadata: BSPData = functools.reduce(lambda a, b: a.metadata.merge(b.metadata), metadata_results)
    digest = await Get(Digest, MergeDigests([r.digest for r in metadata_results]))

    # Determine base directory for this build target.
    # TODO: Use a source root?
    targets_with_sources = [tgt for tgt in targets if tgt.has_field(SourcesField)]
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
