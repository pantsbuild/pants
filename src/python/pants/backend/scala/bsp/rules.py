# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
import textwrap
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
            # TODO: These are the jars for the scalac tool.
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
    wrapped_target = await Get(WrappedTarget, AddressInput, request.bsp_target_id.address_input)
    resolve = wrapped_target.target[JvmResolveField].normalized_value(jvm)
    classfiles_dir_uri = build_root.pathlib_path.joinpath(
        f".pants.d/bsp/jvm/resolves/{resolve}/scala/classes"
    ).as_uri()

    return HandleScalacOptionsResult(
        ScalacOptionsItem(
            target=request.bsp_target_id,
            options=(),
            classpath=(classfiles_dir_uri,),
            class_directory=classfiles_dir_uri,
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
    assert len(coarsened_targets) == 1
    coarsened_target = coarsened_targets[0]
    resolve = await Get(CoursierResolveKey, CoarsenedTargets([coarsened_target]))

    result = await Get(
        FallibleClasspathEntry,
        ClasspathEntryRequest,
        ClasspathEntryRequest.for_targets(
            union_membership, component=coarsened_target, resolve=resolve
        ),
    )
    _logger.info(f"scala compile result = {result}")
    output_digest = EMPTY_DIGEST
    if result.exit_code == 0 and result.output:
        digests: list[Digest] = []
        filenames: list[str] = []
        if result.output:
            digests.append(result.output.digest)
            filenames.extend(result.output.filenames)
        empty_output_dir_digest, script_digest = await MultiGet(
            Get(Digest, CreateDigest([Directory("__classpath__")])),
            Get(
                Digest,
                CreateDigest(
                    [
                        FileContent(
                            "__unpack_jars.sh",
                            textwrap.dedent(
                                f"""\
                            {unzip.path} "$1" -d __classpath__
                            """
                            ).encode(),
                            is_executable=True,
                        )
                    ]
                ),
            ),
        )
        input_digest = await Get(
            Digest, MergeDigests([result.output.digest, empty_output_dir_digest, script_digest])
        )
        unpack_results = await MultiGet(
            Get(
                ProcessResult,
                Process(
                    argv=[bash.path, "./__unpack_jars.sh", filename],
                    description="Unpack classpath",
                    input_digest=input_digest,
                    output_directories=["__classpath__"],
                ),
            )
            for filename in result.output.filenames
        )
        merged_output_digest = await Get(
            Digest, MergeDigests(r.output_digest for r in unpack_results)
        )
        output_digest = await Get(Digest, RemovePrefix(merged_output_digest, "__classpath__"))
        output_digest = await Get(
            Digest, AddPrefix(output_digest, f"bsp/jvm/resolves/{resolve}/scala/classes")
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
