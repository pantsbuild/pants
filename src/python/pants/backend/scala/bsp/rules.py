# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.backend.scala.bsp.spec import (
    ScalaBuildTarget,
    ScalacOptionsItem,
    ScalacOptionsParams,
    ScalacOptionsResult,
    ScalaPlatform,
)
from pants.backend.scala.dependency_inference.symbol_mapper import AllScalaTargets
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.target_types import ScalaSourceField
from pants.base.build_root import BuildRoot
from pants.bsp.context import BSPContext
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import BuildTarget, BuildTargetCapabilities, BuildTargetIdentifier
from pants.bsp.util_rules.compile import BSPCompileFieldSet, BSPCompileResult
from pants.bsp.util_rules.lifecycle import BSPLanguageSupport
from pants.bsp.util_rules.targets import BSPBuildTargets, BSPBuildTargetsRequest
from pants.build_graph.address import AddressInput
from pants.engine.addresses import Addresses
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest, Target, WrappedTarget, CoarsenedTargets
from pants.engine.unions import UnionRule, UnionMembership
from pants.jvm.compile import FallibleClasspathEntry, ClasspathEntryRequest
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField

LANGUAGE_ID = "scala"


class ScalaBSPLanguageSupport(BSPLanguageSupport):
    language_id = LANGUAGE_ID
    can_compile = True


class ScalaBSPBuildTargetsRequest(BSPBuildTargetsRequest):
    pass


@dataclass(frozen=True)
class ResolveScalaBSPBuildTargetRequest:
    target: Target


@rule
async def bsp_resolve_one_scala_build_target(
    request: ResolveScalaBSPBuildTargetRequest,
    jvm: JvmSubsystem,
    scala: ScalaSubsystem,
) -> BuildTarget:
    resolve = request.target[JvmResolveField].normalized_value(jvm)
    scala_version = scala.version_for_resolve(resolve)

    dep_addrs = await Get(Addresses, DependenciesRequest(request.target[Dependencies]))

    return BuildTarget(
        id=BuildTargetIdentifier.from_address(request.target.address),
        display_name=str(request.target.address),
        base_directory=None,
        tags=(),
        capabilities=BuildTargetCapabilities(
            can_compile=True,
        ),
        language_ids=(LANGUAGE_ID,),
        dependencies=tuple(BuildTargetIdentifier.from_address(dep_addr) for dep_addr in dep_addrs),
        data_kind="scala",
        data=ScalaBuildTarget(
            scala_organization="unknown",
            scala_version=".".join(scala_version.split(".")[0:2]),
            scala_binary_version=scala_version,
            platform=ScalaPlatform.JVM,
            jars=(),
        ),
    )


@rule
async def bsp_resolve_all_scala_build_targets(
    _: ScalaBSPBuildTargetsRequest,
    all_scala_targets: AllScalaTargets,
    bsp_context: BSPContext,
) -> BSPBuildTargets:
    if LANGUAGE_ID not in bsp_context.client_params.capabilities.language_ids:
        return BSPBuildTargets()
    build_targets = await MultiGet(
        Get(BuildTarget, ResolveScalaBSPBuildTargetRequest(tgt)) for tgt in all_scala_targets
    )
    return BSPBuildTargets(targets=tuple(build_targets))


# -----------------------------------------------------------------------------------------------
# Scalac Options Request
# See https://build-server-protocol.github.io/docs/extensions/scala.html#scalac-options-request
# -----------------------------------------------------------------------------------------------


class ScalacOptionsHandlerMapping(BSPHandlerMapping):
    method_name = "buildTarget/scalacOptions"
    request_type = ScalacOptionsParams
    response_type = ScalacOptionsResult


@dataclass(frozen=True)
class HandleScalacOptionsRequest:
    bsp_target_id: BuildTargetIdentifier


@dataclass(frozen=True)
class HandleScalacOptionsResult:
    item: ScalacOptionsItem


@rule
async def handle_bsp_scalac_options_request(
    request: HandleScalacOptionsRequest,
    build_root: BuildRoot,
    jvm: JvmSubsystem,
) -> HandleScalacOptionsResult:
    tgt = await Get(WrappedTarget, AddressInput, request.bsp_target_id.address_input)
    resolve = tgt[JvmResolveField].normalized_value(jvm)

    return HandleScalacOptionsResult(
        ScalacOptionsItem(
            target=request.bsp_target_id,
            options=(),
            classpath=(),
            # TODO: Figure out how to provide a classfiles output directory
            class_directory=build_root.pathlib_path.joinpath(f".pants.d/bsp/resolves/{resolve}/classes").as_uri(),
        )
    )


@rule
async def bsp_scalac_options_request(request: ScalacOptionsParams) -> ScalacOptionsResult:
    results = await MultiGet(
        Get(HandleScalacOptionsResult, HandleScalacOptionsRequest(btgt)) for btgt in request.targets
    )
    return ScalacOptionsResult(items=tuple(result.item for result in results))


# -----------------------------------------------------------------------------------------------
# Compile Request
# -----------------------------------------------------------------------------------------------

class ScalaBSPCompileFieldSet(BSPCompileFieldSet):
    required_fields = (ScalaSourceField,)
    sources: ScalaSourceField


@rule
async def bsp_scala_compile_request(request: ScalaBSPCompileFieldSet, union_membership: UnionMembership) -> BSPCompileResult:
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(field_set.address for field_set in request.field_sets)
    )

    # NB: Each root can have an independent resolve, because there is no inherent relation
    # between them other than that they were on the commandline together.
    resolves = await MultiGet(
        Get(CoursierResolveKey, CoarsenedTargets([t])) for t in coarsened_targets
    )

    results = await MultiGet(
        Get(
            FallibleClasspathEntry,
            ClasspathEntryRequest,
            ClasspathEntryRequest.for_targets(union_membership, component=target, resolve=resolve),
        )
        for target, resolve in zip(coarsened_targets, resolves)
    )

    # NB: We don't pass stdout/stderr as it will have already been rendered as streaming.
    exit_code = next((result.exit_code for result in results if result.exit_code != 0), 0)
    return CheckResults([CheckResult(exit_code, "", "")], checker_name=request.name)



def rules():
    return (
        *collect_rules(),
        UnionRule(BSPLanguageSupport, ScalaBSPLanguageSupport),
        UnionRule(BSPBuildTargetsRequest, ScalaBSPBuildTargetsRequest),
        UnionRule(BSPHandlerMapping, ScalacOptionsHandlerMapping),
    )
