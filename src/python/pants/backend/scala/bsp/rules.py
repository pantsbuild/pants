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
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import QueryRule, collect_rules, rule
from pants.engine.target import WrappedTarget
from pants.engine.unions import UnionRule
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField


class ScalaBSPBuildTargetsRequest(BSPBuildTargetsRequest):
    pass


def _pants_target_to_bsp_build_target(
    resolve_field: JvmResolveField, jvm: JvmSubsystem, scala: ScalaSubsystem
) -> BuildTarget:
    resolve = resolve_field.normalized_value(jvm)
    scala_version = scala.version_for_resolve(resolve)
    return BuildTarget(
        id=BuildTargetIdentifier(uri=f"pants:{resolve_field.address}"),
        display_name=str(resolve_field.address),
        base_directory=None,
        tags=(),
        capabilities=BuildTargetCapabilities(),
        language_ids=("scala",),
        dependencies=(),
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
async def determine_scala_bsp_build_targets(
    _: ScalaBSPBuildTargetsRequest,
    all_scala_targets: AllScalaTargets,
    jvm: JvmSubsystem,
    scala: ScalaSubsystem,
) -> BSPBuildTargets:
    scala_bsp_build_targets = [
        _pants_target_to_bsp_build_target(tgt[JvmResolveField], jvm, scala)
        for tgt in all_scala_targets
    ]
    return BSPBuildTargets(targets=tuple(scala_bsp_build_targets))


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
    uri = request.bsp_target_id.uri
    if not uri.startswith("pants:"):
        raise ValueError(f"Unknown URI for Pants BSP: {uri}")
    raw_addr = uri[len("pants:") :]

    # Verify the target exists by loading it. Exception will be thrown if it does not.
    _ = await Get(WrappedTarget, AddressInput, AddressInput.parse(raw_addr))

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
