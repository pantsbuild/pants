# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
import logging
import os
from dataclasses import dataclass

from pants.backend.scala.bsp.spec import (
    ScalaBuildTarget,
    ScalacOptionsItem,
    ScalacOptionsParams,
    ScalacOptionsResult,
    ScalaPlatform,
)
from pants.backend.scala.compile.scalac import compute_output_jar_filename
from pants.backend.scala.dependency_inference.symbol_mapper import AllScalaTargets
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.target_types import ScalaSourceField
from pants.base.build_root import BuildRoot
from pants.bsp.context import BSPContext
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import (
    BuildTarget,
    BuildTargetCapabilities,
    BuildTargetIdentifier,
    StatusCode,
)
from pants.bsp.util_rules.compile import BSPCompileFieldSet, BSPCompileResult
from pants.bsp.util_rules.lifecycle import BSPLanguageSupport
from pants.bsp.util_rules.targets import BSPBuildTargets, BSPBuildTargetsRequest
from pants.build_graph.address import Address, AddressInput
from pants.engine.addresses import Addresses
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, CreateDigest, Digest, DigestEntries
from pants.engine.internals.native_engine import MergeDigests, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    CoarsenedTargets,
    Dependencies,
    DependenciesRequest,
    Target,
    WrappedTarget,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.jvm.compile import (
    ClasspathEntryRequest,
    ClasspathEntryRequestFactory,
    FallibleClasspathEntry,
)
from pants.jvm.resolve.common import ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField

LANGUAGE_ID = "scala"

_logger = logging.getLogger(__name__)


class ScalaBSPLanguageSupport(BSPLanguageSupport):
    language_id = LANGUAGE_ID
    can_compile = True


class ScalaBSPBuildTargetsRequest(BSPBuildTargetsRequest):
    pass


@dataclass(frozen=True)
class ResolveScalaBSPBuildTargetRequest:
    target: Target


@dataclass(frozen=True)
class ResolveScalaBSPBuildTargetResult:
    build_target: BuildTarget
    scala_runtime: Snapshot


@dataclass(frozen=True)
class MaterializeScalaRuntimeJarsRequest:
    scala_version: str


@dataclass(frozen=True)
class MaterializeScalaRuntimeJarsResult:
    content: Snapshot


@rule
async def materialize_scala_runtime_jars(
    request: MaterializeScalaRuntimeJarsRequest,
) -> MaterializeScalaRuntimeJarsResult:
    tool_classpath = await Get(
        ToolClasspath,
        ToolClasspathRequest(
            artifact_requirements=ArtifactRequirements.from_coordinates(
                [
                    Coordinate(
                        group="org.scala-lang",
                        artifact="scala-compiler",
                        version=request.scala_version,
                    ),
                    Coordinate(
                        group="org.scala-lang",
                        artifact="scala-library",
                        version=request.scala_version,
                    ),
                ]
            ),
        ),
    )

    materialized_classpath_digest = await Get(
        Digest,
        AddPrefix(tool_classpath.content.digest, f"jvm/scala-runtime/{request.scala_version}"),
    )
    materialized_classpath = await Get(Snapshot, Digest, materialized_classpath_digest)
    return MaterializeScalaRuntimeJarsResult(materialized_classpath)


@rule
async def bsp_resolve_one_scala_build_target(
    request: ResolveScalaBSPBuildTargetRequest,
    jvm: JvmSubsystem,
    scala: ScalaSubsystem,
    union_membership: UnionMembership,
    build_root: BuildRoot,
) -> ResolveScalaBSPBuildTargetResult:
    resolve = request.target[JvmResolveField].normalized_value(jvm)
    scala_version = scala.version_for_resolve(resolve)

    dep_addrs, scala_runtime = await MultiGet(
        Get(Addresses, DependenciesRequest(request.target[Dependencies])),
        Get(MaterializeScalaRuntimeJarsResult, MaterializeScalaRuntimeJarsRequest(scala_version)),
    )
    impls = union_membership.get(BSPCompileFieldSet)

    reported_deps = []
    for dep_addr in dep_addrs:
        if dep_addr == request.target.address:
            continue

        wrapped_dep_tgt = await Get(WrappedTarget, Address, dep_addr)
        dep_tgt = wrapped_dep_tgt.target
        for impl in impls:
            if impl.is_applicable(dep_tgt):
                reported_deps.append(BuildTargetIdentifier.from_address(dep_tgt.address))
                break

    scala_jar_uris = tuple(
        build_root.pathlib_path.joinpath(".pants.d/bsp").joinpath(p).as_uri()
        for p in scala_runtime.content.files
    )
    bsp_target = BuildTarget(
        id=BuildTargetIdentifier.from_address(request.target.address),
        display_name=str(request.target.address),
        base_directory=None,
        tags=(),
        capabilities=BuildTargetCapabilities(
            can_compile=True,
        ),
        language_ids=(LANGUAGE_ID,),
        dependencies=tuple(reported_deps),
        data_kind="scala",
        data=ScalaBuildTarget(
            scala_organization="unknown",
            scala_version=scala_version,
            scala_binary_version=".".join(scala_version.split(".")[0:2]),
            platform=ScalaPlatform.JVM,
            jars=scala_jar_uris,
        ),
    )
    return ResolveScalaBSPBuildTargetResult(bsp_target, scala_runtime=scala_runtime.content)


@rule
async def bsp_resolve_all_scala_build_targets(
    _: ScalaBSPBuildTargetsRequest,
    all_scala_targets: AllScalaTargets,
    bsp_context: BSPContext,
) -> BSPBuildTargets:
    if LANGUAGE_ID not in bsp_context.client_params.capabilities.language_ids:
        return BSPBuildTargets()
    build_targets = await MultiGet(
        Get(ResolveScalaBSPBuildTargetResult, ResolveScalaBSPBuildTargetRequest(tgt))
        for tgt in all_scala_targets
    )
    output_digest = await Get(Digest, MergeDigests([d.scala_runtime.digest for d in build_targets]))
    return BSPBuildTargets(
        targets=tuple(btgt.build_target for btgt in build_targets), digest=output_digest
    )


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
) -> HandleScalacOptionsResult:
    wrapped_target = await Get(WrappedTarget, AddressInput, request.bsp_target_id.address_input)
    coarsened_targets = await Get(CoarsenedTargets, Addresses([wrapped_target.target.address]))
    assert len(coarsened_targets) == 1
    coarsened_target = coarsened_targets[0]
    resolve = await Get(CoursierResolveKey, CoarsenedTargets([coarsened_target]))
    output_file = compute_output_jar_filename(coarsened_target)

    return HandleScalacOptionsResult(
        ScalacOptionsItem(
            target=request.bsp_target_id,
            options=(),
            classpath=(
                build_root.pathlib_path.joinpath(
                    f".pants.d/bsp/jvm/resolves/{resolve.name}/lib/{output_file}"
                ).as_uri(),
            ),
            class_directory=build_root.pathlib_path.joinpath(
                f".pants.d/bsp/jvm/resolves/{resolve.name}/classes"
            ).as_uri(),
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


@dataclass(frozen=True)
class ScalaBSPCompileFieldSet(BSPCompileFieldSet):
    required_fields = (ScalaSourceField,)
    source: ScalaSourceField


@rule
async def bsp_scala_compile_request(
    request: ScalaBSPCompileFieldSet,
    classpath_entry_request: ClasspathEntryRequestFactory,
) -> BSPCompileResult:
    coarsened_targets = await Get(CoarsenedTargets, Addresses([request.source.address]))
    assert len(coarsened_targets) == 1
    coarsened_target = coarsened_targets[0]
    resolve = await Get(CoursierResolveKey, CoarsenedTargets([coarsened_target]))

    result = await Get(
        FallibleClasspathEntry,
        ClasspathEntryRequest,
        classpath_entry_request.for_targets(component=coarsened_target, resolve=resolve),
    )
    _logger.info(f"scala compile result = {result}")
    output_digest = EMPTY_DIGEST
    if result.exit_code == 0 and result.output:
        entries = await Get(DigestEntries, Digest, result.output.digest)
        new_entires = [
            dataclasses.replace(entry, path=os.path.basename(entry.path)) for entry in entries
        ]
        flat_digest = await Get(Digest, CreateDigest(new_entires))
        output_digest = await Get(
            Digest, AddPrefix(flat_digest, f"jvm/resolves/{resolve.name}/lib")
        )

    return BSPCompileResult(
        status=StatusCode.ERROR if result.exit_code != 0 else StatusCode.OK,
        output_digest=output_digest,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(BSPLanguageSupport, ScalaBSPLanguageSupport),
        UnionRule(BSPBuildTargetsRequest, ScalaBSPBuildTargetsRequest),
        UnionRule(BSPHandlerMapping, ScalacOptionsHandlerMapping),
        UnionRule(BSPCompileFieldSet, ScalaBSPCompileFieldSet),
    )
