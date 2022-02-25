# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import time
from dataclasses import dataclass

from pants.base.build_root import BuildRoot
from pants.bsp.context import BSPContext
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec import (
    BuildServerCapabilities,
    BuildTarget,
    BuildTargetIdentifier,
    CompileParams,
    CompileProvider,
    CompileReport,
    CompileResult,
    CompileTask,
    DebugProvider,
    InitializeBuildParams,
    InitializeBuildResult,
    RunProvider,
    SourceItem,
    SourceItemKind,
    SourcesItem,
    SourcesParams,
    SourcesResult,
    StatusCode,
    TaskFinishParams,
    TaskId,
    TaskStartParams,
    TestProvider,
    WorkspaceBuildTargetsParams,
    WorkspaceBuildTargetsResult,
)
from pants.bsp.types import BSPLanguageSupport
from pants.build_graph.address import AddressInput
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.internals.session import SessionValues
from pants.engine.rules import collect_rules, rule
from pants.engine.target import SourcesField, SourcesPaths, SourcesPathsRequest, WrappedTarget
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.version import VERSION

# Version of BSP supported by Pants.
BSP_VERSION = "2.0.0"


@rule
async def bsp_context(session_values: SessionValues) -> BSPContext:
    return session_values[BSPContext]


@union
class BSPBuildTargetsRequest:
    """Request language backends to provide BSP `BuildTarget` instances for their managed target
    types."""


@dataclass(frozen=True)
class BSPBuildTargets:
    targets: tuple[BuildTarget, ...] = ()


# -----------------------------------------------------------------------------------------------
# Initialize Build Request
# See https://build-server-protocol.github.io/docs/specification.html#initialize-build-request
# -----------------------------------------------------------------------------------------------


class InitializeBuildHandlerMapping(BSPHandlerMapping):
    method_name = "build/initialize"
    request_type = InitializeBuildParams
    response_type = InitializeBuildResult


@rule
async def bsp_build_initialize(
    _request: InitializeBuildParams, union_membership: UnionMembership
) -> InitializeBuildResult:
    compile_provider_language_ids = []
    test_provider_language_ids = []
    run_provider_language_ids = []
    debug_provider_language_ids = []
    language_support_impls = union_membership.get(BSPLanguageSupport)
    for lang in language_support_impls:
        if lang.can_compile:
            compile_provider_language_ids.append(lang.language_id)
        if lang.can_test:
            test_provider_language_ids.append(lang.language_id)
        if lang.can_run:
            run_provider_language_ids.append(lang.language_id)
        if lang.can_debug:
            debug_provider_language_ids.append(lang.language_id)

    return InitializeBuildResult(
        display_name="Pants",
        version=VERSION,
        bsp_version=BSP_VERSION,  # TODO: replace with an actual BSP version
        capabilities=BuildServerCapabilities(
            compile_provider=CompileProvider(
                language_ids=tuple(sorted(compile_provider_language_ids))
            ),
            test_provider=TestProvider(language_ids=tuple(sorted(test_provider_language_ids))),
            run_provider=RunProvider(language_ids=tuple(sorted(run_provider_language_ids))),
            debug_provider=DebugProvider(language_ids=tuple(sorted(debug_provider_language_ids))),
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


class WorkspaceBuildTargetsHandlerMapping(BSPHandlerMapping):
    method_name = "workspace/buildTargets"
    request_type = WorkspaceBuildTargetsParams
    response_type = WorkspaceBuildTargetsResult


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
# Compile Request
# See https://build-server-protocol.github.io/docs/specification.html#compile-request
# -----------------------------------------------------------------------------------------------


class CompileRequestHandlerMapping(BSPHandlerMapping):
    method_name = "buildTarget/compile"
    request_type = CompileParams
    response_type = CompileResult


@rule
async def bsp_compile_request(request: CompileParams, bsp_context: BSPContext) -> CompileResult:
    origin_id = request.origin_id or "compile-task"
    for i, target in enumerate(request.targets):
        task_id = TaskId(id=f"{origin_id}-{i}")
        bsp_context.notify_client(
            TaskStartParams(
                task_id=task_id,
                event_time=int(time.time() * 1000),
                data=CompileTask(target=target),
            )
        )

    for i, target in enumerate(request.targets):
        task_id = TaskId(id=f"{origin_id}-{i}")
        bsp_context.notify_client(
            TaskFinishParams(
                task_id=task_id,
                status=StatusCode.ERROR,
                data=CompileReport(target=target, origin_id=origin_id),
            )
        )

    return CompileResult(
        origin_id=request.origin_id,
        status_code=1,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(BSPHandlerMapping, InitializeBuildHandlerMapping),
        UnionRule(BSPHandlerMapping, WorkspaceBuildTargetsHandlerMapping),
        UnionRule(BSPHandlerMapping, BuildTargetSourcesHandlerMapping),
        UnionRule(BSPHandlerMapping, CompileRequestHandlerMapping),
    )
