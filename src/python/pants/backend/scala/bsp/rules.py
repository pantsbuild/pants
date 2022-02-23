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
from pants.base.build_root import BuildRoot
from pants.bsp.rules import BSPBuildTargets, BSPBuildTargetsRequest
from pants.bsp.spec import BuildTarget, BuildTargetCapabilities, BuildTargetIdentifier
from pants.build_graph.address import AddressInput
from pants.engine.addresses import Addresses
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import QueryRule, collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest, Target, WrappedTarget
from pants.engine.unions import UnionRule
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField


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
        capabilities=BuildTargetCapabilities(),
        language_ids=("scala",),
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
    jvm: JvmSubsystem,
    scala: ScalaSubsystem,
) -> BSPBuildTargets:
    build_targets = await MultiGet(
        Get(BuildTarget, ResolveScalaBSPBuildTargetRequest(tgt)) for tgt in all_scala_targets
    )
    return BSPBuildTargets(targets=tuple(build_targets))


# -----------------------------------------------------------------------------------------------
# Scalac Options Request
# See https://build-server-protocol.github.io/docs/extensions/scala.html#scalac-options-request
# -----------------------------------------------------------------------------------------------


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
) -> HandleScalacOptionsResult:
    # Verify the target exists by loading it. Exception will be thrown if it does not.
    _ = await Get(WrappedTarget, AddressInput, request.bsp_target_id.address_input)

    return HandleScalacOptionsResult(
        ScalacOptionsItem(
            target=request.bsp_target_id,
            options=(),
            classpath=(),
            # TODO: Figure out how to provide a classfiles output directory
            class_directory=build_root.pathlib_path.joinpath("dist/bsp").as_uri(),
        )
    )


@rule
async def bsp_scalac_options_request(request: ScalacOptionsParams) -> ScalacOptionsResult:
    results = await MultiGet(
        Get(HandleScalacOptionsResult, HandleScalacOptionsRequest(btgt)) for btgt in request.targets
    )
    return ScalacOptionsResult(items=tuple(result.item for result in results))


def rules():
    return (
        *collect_rules(),
        UnionRule(BSPBuildTargetsRequest, ScalaBSPBuildTargetsRequest),
        QueryRule(ScalacOptionsResult, (ScalacOptionsParams,)),
    )
