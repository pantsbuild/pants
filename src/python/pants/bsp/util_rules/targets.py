# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Generic, Sequence, Type, TypeVar

import toml

from pants.base.build_root import BuildRoot
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import RawSpecs, RawSpecsWithoutFileOwners
from pants.base.specs_parser import SpecsParser
from pants.bsp.goal import BSPGoal
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import (
    BSPData,
    BuildTarget,
    BuildTargetCapabilities,
    BuildTargetIdentifier,
    StatusCode,
    TaskId,
    Uri,
)
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
from pants.engine.environment import EnvironmentName
from pants.engine.fs import DigestContents, PathGlobs, Workspace
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import _uncacheable_rule, collect_rules, rule
from pants.engine.target import (
    Field,
    FieldDefaults,
    FieldSet,
    SourcesField,
    SourcesPaths,
    SourcesPathsRequest,
    Targets,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.source.source_root import SourceRootsRequest, SourceRootsResult
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import bullet_list

_logger = logging.getLogger(__name__)

_FS = TypeVar("_FS", bound=FieldSet)


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class BSPBuildTargetsMetadataRequest(Generic[_FS]):
    """Hook to allow language backends to provide metadata for BSP build targets."""

    language_id: ClassVar[str]
    can_merge_metadata_from: ClassVar[tuple[str, ...]]
    field_set_type: ClassVar[Type[_FS]]  # type: ignore[misc]

    resolve_prefix: ClassVar[str]
    resolve_field: ClassVar[type[Field]]

    field_sets: tuple[_FS, ...]


@dataclass(frozen=True)
class BSPBuildTargetsMetadataResult:
    """Response type for a BSPBuildTargetsMetadataRequest."""

    # Metadata for the `data` field of the final `BuildTarget`.
    metadata: BSPData | None = None

    # Output to write into `.pants.d/bsp` for access by IDE.
    digest: Digest = EMPTY_DIGEST


@dataclass(frozen=True)
class BSPTargetDefinition:
    display_name: str | None
    base_directory: str | None
    addresses: tuple[str, ...]
    resolve_filter: str | None


@dataclass(frozen=True)
class BSPBuildTargetInternal:
    name: str
    specs: RawSpecs
    definition: BSPTargetDefinition

    @property
    def bsp_target_id(self) -> BuildTargetIdentifier:
        return BuildTargetIdentifier(f"pants:{self.name}")


@dataclass(frozen=True)
class BSPBuildTargetSourcesInfo:
    """Source files and roots for a BSP build target.

    It is a separate class so that it is computed lazily only when called for by an RPC call.
    """

    source_files: frozenset[str]
    source_roots: frozenset[str]


@dataclass(frozen=True)
class BSPBuildTargets:
    targets_mapping: FrozenDict[str, BSPBuildTargetInternal]


@dataclass(frozen=True)
class _ParseOneBSPMappingRequest:
    name: str
    definition: BSPTargetDefinition


@rule
async def parse_one_bsp_mapping(request: _ParseOneBSPMappingRequest) -> BSPBuildTargetInternal:
    specs_parser = SpecsParser()
    specs = specs_parser.parse_specs(
        request.definition.addresses, description_of_origin=f"the BSP mapping {request.name}"
    ).includes
    return BSPBuildTargetInternal(request.name, specs, request.definition)


@rule
async def materialize_bsp_build_targets(bsp_goal: BSPGoal) -> BSPBuildTargets:
    definitions: dict[str, BSPTargetDefinition] = {}
    for config_file in bsp_goal.groups_config_files:
        config_contents = await Get(  # noqa: PNT30: requires triage
            DigestContents,
            PathGlobs(
                [config_file],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=f"BSP config file `{config_file}`",
            ),
        )
        if len(config_contents) == 0:
            raise ValueError(f"BSP targets config file `{config_file}` does not exist.")
        elif len(config_contents) > 1:
            raise ValueError(
                f"BSP targets config file specified as `{config_file}` matches multiple files. "
                "Please do not use wildcards in config file paths."
            )

        config = toml.loads(config_contents[0].content.decode())

        groups = config.get("groups")
        if groups is None:
            raise ValueError(
                f"BSP targets config file `{config_file}` is missing the `groups` table."
            )
        if not isinstance(groups, dict):
            raise ValueError(
                f"BSP targets config file `{config_file}` contains a `groups` key that is not a TOML table."
            )

        for id, group in groups.items():
            if not isinstance(group, dict):
                raise ValueError(
                    f"BSP targets config file `{config_file}` contains an entry for "
                    "`groups` array that is not a dictionary (index={i})."
                )

            base_directory = group.get("base_directory")
            display_name = group.get("display_name")
            addresses = group.get("addresses", [])
            if not addresses:
                raise ValueError(
                    f"BSP targets config file `{config_file}` contains group ID `{id}` which has "
                    "no address specs defined via the `addresses` key. Please specify at least "
                    "one address spec."
                )

            resolve_filter = group.get("resolve")

            definitions[id] = BSPTargetDefinition(
                display_name=display_name,
                base_directory=base_directory,
                addresses=tuple(addresses),
                resolve_filter=resolve_filter,
            )

    bsp_internal_targets = await MultiGet(
        Get(BSPBuildTargetInternal, _ParseOneBSPMappingRequest(name, definition))
        for name, definition in definitions.items()
    )
    target_mapping = dict(zip(definitions.keys(), bsp_internal_targets))
    return BSPBuildTargets(FrozenDict(target_mapping))


@rule
async def resolve_bsp_build_target_identifier(
    bsp_target_id: BuildTargetIdentifier, bsp_build_targets: BSPBuildTargets
) -> BSPBuildTargetInternal:
    scheme, _, target_name = bsp_target_id.uri.partition(":")
    if scheme != "pants":
        raise ValueError(f"Unknown BSP scheme `{scheme}` for BSP target ID `{bsp_target_id}.")

    target_internal = bsp_build_targets.targets_mapping.get(target_name)
    if not target_internal:
        raise ValueError(f"Unknown BSP target name: {target_name}")

    return target_internal


@rule
async def resolve_bsp_build_target_addresses(
    bsp_target: BSPBuildTargetInternal,
    union_membership: UnionMembership,
    field_defaults: FieldDefaults,
) -> Targets:
    # NB: Using `RawSpecs` directly rather than `RawSpecsWithoutFileOwners` results in a rule graph cycle.
    targets = await Get(
        Targets,
        RawSpecsWithoutFileOwners,
        RawSpecsWithoutFileOwners.from_raw_specs(bsp_target.specs),
    )
    if bsp_target.definition.resolve_filter is None:
        return targets

    resolve_filter = bsp_target.definition.resolve_filter
    resolve_prefix, matched, resolve_value = resolve_filter.partition(":")
    if not resolve_prefix or not matched:
        raise ValueError(
            f"The `resolve` filter for `{bsp_target}` must have a platform or language specific "
            f"prefix like `$lang:$filter`, but the configured value: `{resolve_filter}` did not."
        )

    resolve_fields = {
        impl.resolve_field
        for impl in union_membership.get(BSPBuildTargetsMetadataRequest)
        if impl.resolve_prefix == resolve_prefix
    }

    return Targets(
        t
        for t in targets
        if any(
            t.has_field(field) and field_defaults.value_or_default(t[field]) == resolve_value
            for field in resolve_fields
        )
    )


@rule
async def resolve_bsp_build_target_source_roots(
    bsp_target: BSPBuildTargetInternal,
) -> BSPBuildTargetSourcesInfo:
    targets = await Get(Targets, BSPBuildTargetInternal, bsp_target)
    targets_with_sources = [tgt for tgt in targets if tgt.has_field(SourcesField)]
    sources_paths = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(tgt[SourcesField])) for tgt in targets_with_sources
    )
    merged_source_files: set[str] = set()
    for sp in sources_paths:
        merged_source_files.update(sp.files)
    source_roots_result = await Get(
        SourceRootsResult, SourceRootsRequest, SourceRootsRequest.for_files(merged_source_files)
    )
    source_root_paths = {x.path for x in source_roots_result.path_to_root.values()}
    return BSPBuildTargetSourcesInfo(
        source_files=frozenset(merged_source_files),
        source_roots=frozenset(source_root_paths),
    )


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


def merge_metadata(
    metadata_results_by_request_type: Sequence[
        tuple[type[BSPBuildTargetsMetadataRequest], BSPBuildTargetsMetadataResult]
    ],
) -> BSPData | None:
    if not metadata_results_by_request_type:
        return None
    if len(metadata_results_by_request_type) == 1:
        return metadata_results_by_request_type[0][1].metadata

    # Naive algorithm (since we only support Java and Scala backends), find the metadata request type that cannot
    # merge from another and use that one.
    if len(metadata_results_by_request_type) != 2:
        raise AssertionError(
            "BSP core rules only support naive ordering of language-backend metadata. Contact Pants developers."
        )
    if not metadata_results_by_request_type[0][0].can_merge_metadata_from:
        metadata_index = 1
    elif not metadata_results_by_request_type[1][0].can_merge_metadata_from:
        metadata_index = 0
    else:
        raise AssertionError(
            "BSP core rules only support naive ordering of language-backend metadata. Contact Pants developers."
        )

    # Pretend to merge the metadata into a single piece of metadata, but really just choose the metadata
    # from the selected provider.
    return metadata_results_by_request_type[metadata_index][1].metadata


@rule
async def generate_one_bsp_build_target_request(
    request: GenerateOneBSPBuildTargetRequest,
    union_membership: UnionMembership,
    build_root: BuildRoot,
) -> GenerateOneBSPBuildTargetResult:
    # Find all Pants targets that are part of this BSP build target.
    targets = await Get(Targets, BSPBuildTargetInternal, request.bsp_target)

    # Determine whether the targets are compilable.
    can_compile = any(
        req_type.field_set_type.is_applicable(t)  # type: ignore[misc]
        for req_type in union_membership[BSPCompileRequest]
        for t in targets
    )

    # Classify the targets by the language backends that claim to provide metadata for them.
    field_sets_by_request_type: dict[
        type[BSPBuildTargetsMetadataRequest], OrderedSet[FieldSet]
    ] = defaultdict(OrderedSet)
    metadata_request_types: FrozenOrderedSet[
        Type[BSPBuildTargetsMetadataRequest]
    ] = union_membership.get(BSPBuildTargetsMetadataRequest)
    metadata_request_types_by_lang_id: dict[str, type[BSPBuildTargetsMetadataRequest]] = {}
    for metadata_request_type in metadata_request_types:
        previous = metadata_request_types_by_lang_id.get(metadata_request_type.language_id)
        if previous:
            raise ValueError(
                f"Multiple implementations claim to support `{metadata_request_type.language_id}`:"
                f"{bullet_list([previous.__name__, metadata_request_type.__name__])}"
                "\n"
                "Do you have conflicting language support backends enabled?"
            )
        metadata_request_types_by_lang_id[metadata_request_type.language_id] = metadata_request_type

    for tgt in targets:
        for metadata_request_type in metadata_request_types:
            field_set_type: Type[FieldSet] = metadata_request_type.field_set_type
            if field_set_type.is_applicable(tgt):
                field_sets_by_request_type[metadata_request_type].add(field_set_type.create(tgt))

    # Request each language backend to provide metadata for the BuildTarget, and then merge it.
    metadata_results = await MultiGet(
        Get(
            BSPBuildTargetsMetadataResult,
            BSPBuildTargetsMetadataRequest,
            request_type(field_sets=tuple(field_sets)),
        )
        for request_type, field_sets in field_sets_by_request_type.items()
    )
    metadata = merge_metadata(list(zip(field_sets_by_request_type.keys(), metadata_results)))

    digest = await Get(Digest, MergeDigests([r.digest for r in metadata_results]))

    # Determine "base directory" for this build target using source roots.
    # TODO: This actually has nothing to do with source roots. It should probably be computed as an ancestor
    # directory or else be configurable by the user. It is used as a hint in IntelliJ for where to place the
    # corresponding IntelliJ module.
    source_info = await Get(BSPBuildTargetSourcesInfo, BSPBuildTargetInternal, request.bsp_target)
    if source_info.source_roots:
        roots = [build_root.pathlib_path.joinpath(p) for p in source_info.source_roots]
    else:
        roots = []

    base_directory: Path | None = None
    if request.bsp_target.definition.base_directory:
        base_directory = build_root.pathlib_path.joinpath(
            request.bsp_target.definition.base_directory
        )
    elif roots:
        base_directory = roots[0]

    return GenerateOneBSPBuildTargetResult(
        build_target=BuildTarget(
            id=BuildTargetIdentifier(f"pants:{request.bsp_target.name}"),
            display_name=request.bsp_target.name,
            base_directory=base_directory.as_uri() if base_directory else None,
            tags=(),
            capabilities=BuildTargetCapabilities(
                can_compile=can_compile,
                can_debug=False,
                # TODO: See https://github.com/pantsbuild/pants/issues/15050.
                can_run=False,
                can_test=False,
            ),
            language_ids=tuple(sorted(req.language_id for req in field_sets_by_request_type)),
            dependencies=(),
            data=metadata,
        ),
        digest=digest,
    )


@_uncacheable_rule
async def bsp_workspace_build_targets(
    _: WorkspaceBuildTargetsParams,
    bsp_build_targets: BSPBuildTargets,
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
) -> MaterializeBuildTargetSourcesResult:
    bsp_target = await Get(BSPBuildTargetInternal, BuildTargetIdentifier, request.bsp_target_id)
    source_info = await Get(BSPBuildTargetSourcesInfo, BSPBuildTargetInternal, bsp_target)

    if source_info.source_roots:
        roots = [build_root.pathlib_path.joinpath(p) for p in source_info.source_roots]
    else:
        roots = [build_root.pathlib_path]

    sources_item = SourcesItem(
        target=request.bsp_target_id,
        sources=tuple(
            SourceItem(
                uri=build_root.pathlib_path.joinpath(filename).as_uri(),
                kind=SourceItemKind.FILE,
                generated=False,
            )
            for filename in sorted(source_info.source_files)
        ),
        roots=tuple(r.as_uri() for r in roots),
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


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class BSPDependencyModulesRequest(Generic[_FS]):
    """Hook to allow language backends to provide dependency modules."""

    field_set_type: ClassVar[Type[_FS]]  # type: ignore[misc]

    field_sets: tuple[_FS, ...]


@dataclass(frozen=True)
class BSPDependencyModulesResult:
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
    targets = await Get(Targets, BuildTargetIdentifier, request.bsp_target_id)

    field_sets_by_request_type: dict[
        Type[BSPDependencyModulesRequest], list[FieldSet]
    ] = defaultdict(list)
    dep_module_request_types: FrozenOrderedSet[
        Type[BSPDependencyModulesRequest]
    ] = union_membership.get(BSPDependencyModulesRequest)
    for tgt in targets:
        for dep_module_request_type in dep_module_request_types:
            field_set_type = dep_module_request_type.field_set_type
            if field_set_type.is_applicable(tgt):
                field_set = field_set_type.create(tgt)
                field_sets_by_request_type[dep_module_request_type].append(field_set)

    if not field_sets_by_request_type:
        return ResolveOneDependencyModuleResult(bsp_target_id=request.bsp_target_id)

    responses = await MultiGet(
        Get(
            BSPDependencyModulesResult,
            BSPDependencyModulesRequest,
            dep_module_request_type(field_sets=tuple(field_sets)),
        )
        for dep_module_request_type, field_sets in field_sets_by_request_type.items()
    )

    modules = set(itertools.chain.from_iterable([r.modules for r in responses]))
    digest = await Get(Digest, MergeDigests([r.digest for r in responses]))

    return ResolveOneDependencyModuleResult(
        bsp_target_id=request.bsp_target_id,
        modules=tuple(modules),
        digest=digest,
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


# -----------------------------------------------------------------------------------------------
# Compile request.
# See https://build-server-protocol.github.io/docs/specification.html#compile-request
# -----------------------------------------------------------------------------------------------


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class BSPCompileRequest(Generic[_FS]):
    """Hook to allow language backends to compile targets."""

    field_set_type: ClassVar[Type[_FS]]  # type: ignore[misc]

    bsp_target: BSPBuildTargetInternal
    field_sets: tuple[_FS, ...]
    task_id: TaskId


@dataclass(frozen=True)
class BSPCompileResult:
    """Result of compilation of a target capable of target compilation."""

    status: StatusCode
    output_digest: Digest


# -----------------------------------------------------------------------------------------------
# Resources request.
# See https://build-server-protocol.github.io/docs/specification.html#resources-request
#
# NB: This method is used only for the _indexing_ of resources, and not to add them to the
# classpath (in the case of JVM targets). BSPCompileRequest implementations need to handle
# movement of resources to accessible classpath entries.
# -----------------------------------------------------------------------------------------------


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class BSPResourcesRequest(Generic[_FS]):
    """Hook to allow language backends to provide resources for targets."""

    field_set_type: ClassVar[Type[_FS]]  # type: ignore[misc]

    bsp_target: BSPBuildTargetInternal
    field_sets: tuple[_FS, ...]


@dataclass(frozen=True)
class BSPResourcesResult:
    """Resources for a target."""

    resources: tuple[Uri, ...]
    output_digest: Digest


def rules():
    return (
        *collect_rules(),
        UnionRule(BSPHandlerMapping, WorkspaceBuildTargetsHandlerMapping),
        UnionRule(BSPHandlerMapping, BuildTargetSourcesHandlerMapping),
        UnionRule(BSPHandlerMapping, DependencySourcesHandlerMapping),
        UnionRule(BSPHandlerMapping, DependencyModulesHandlerMapping),
    )
