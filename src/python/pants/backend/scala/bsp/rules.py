# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
import textwrap
from dataclasses import dataclass
from pathlib import PurePath

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
from pants.bsp.spec.base import (
    BuildTarget,
    BuildTargetCapabilities,
    BuildTargetIdentifier,
    StatusCode,
)
from pants.bsp.util_rules.compile import BSPCompileFieldSet, BSPCompileResult
from pants.bsp.util_rules.lifecycle import BSPLanguageSupport
from pants.bsp.util_rules.targets import BSPBuildTargets, BSPBuildTargetsRequest
from pants.build_graph.address import AddressInput
from pants.core.util_rules.system_binaries import BashBinary, UnzipBinary
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    FileContent,
    MergeDigests,
    RemovePrefix,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    CoarsenedTargets,
    Dependencies,
    DependenciesRequest,
    Target,
    WrappedTarget,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.jvm.compile import ClasspathEntryRequest, FallibleClasspathEntry
from pants.jvm.resolve.common import ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile
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
class ScalacSDKRequest:
    scala_version: str


@dataclass(frozen=True)
class ScalacSDKResult:
    scala_build_target: ScalaBuildTarget


@rule
async def bsp_resolve_one_scala_build_target(
    request: ResolveScalaBSPBuildTargetRequest,
    jvm: JvmSubsystem,
    scala: ScalaSubsystem,
) -> BuildTarget:
    resolve = request.target[JvmResolveField].normalized_value(jvm)
    scala_version = scala.version_for_resolve(resolve)

    dep_addrs, scalac_sdk = await MultiGet(
        Get(Addresses, DependenciesRequest(request.target[Dependencies])),
        Get(ScalacSDKResult, ScalacSDKRequest(scala_version)),
    )

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
        data=scalac_sdk.scala_build_target,
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


@rule
async def resolve_scalac_sdk(request: ScalacSDKRequest) -> ScalacSDKResult:
    scalac_resolution = await Get(
        CoursierResolvedLockfile,
        ArtifactRequirements,
        ArtifactRequirements.from_coordinates(
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
    )

    scala_build_target = ScalaBuildTarget(
        scala_organization="unknown",
        scala_version=".".join(request.scala_version.split(".")[0:2]),
        scala_binary_version=request.scala_version,
        platform=ScalaPlatform.JVM,
        jars=tuple(PurePath(path).as_uri() for path in scalac_resolution.artifact_cache_uris),
    )

    return ScalacSDKResult(scala_build_target)


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
    _ = await Get(WrappedTarget, AddressInput, request.bsp_target_id.address_input)

    return HandleScalacOptionsResult(
        ScalacOptionsItem(
            target=request.bsp_target_id,
            options=(),
            classpath=(),
            class_directory=build_root.pathlib_path.joinpath(".pants.d/bsp/scala/classes").as_uri(),
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
    union_membership: UnionMembership,
    unzip: UnzipBinary,
    bash: BashBinary,
) -> BSPCompileResult:
    coarsened_targets = await Get(CoarsenedTargets, Addresses([request.source.address]))

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
    _logger.info(f"results = {results}")

    exit_code = next((result.exit_code for result in results if result.exit_code != 0), 0)
    _logger.info(f"exit code = {exit_code}")
    output_digest = EMPTY_DIGEST
    if exit_code == 0:
        digests: list[Digest] = []
        filenames: list[str] = []
        for result in results:
            if result.output:
                digests.append(result.output.digest)
                filenames.extend(result.output.filenames)
        jars_digest = await Get(Digest, MergeDigests(digests))
        input_digest = await Get(Digest, CreateDigest([Directory("__classpath__")]))
        script_digest = await Get(
            Digest,
            CreateDigest(
                [
                    FileContent(
                        "__unpack_jars.sh",
                        textwrap.dedent(
                            f"""\
                for filename in {' '.join(filenames)} ; do
                  {unzip.path} $filename -d __classpath__
                done
                """
                        ).encode(),
                        is_executable=True,
                    )
                ]
            ),
        )
        input_digest = await Get(Digest, MergeDigests([input_digest, script_digest, jars_digest]))
        unpack_result = await Get(
            ProcessResult,
            Process(
                argv=[bash.path, "./__unpack_jars.sh"],
                description="Unpack classpath",
                input_digest=input_digest,
                output_directories=["__classpath__"],
            ),
        )
        output_digest = await Get(
            Digest, RemovePrefix(unpack_result.output_digest, "__classpath__")
        )
        output_digest = await Get(Digest, AddPrefix(output_digest, "scala/classes"))

    return BSPCompileResult(
        status=StatusCode.ERROR if exit_code != 0 else StatusCode.OK,
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
