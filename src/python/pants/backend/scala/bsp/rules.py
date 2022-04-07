# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass

from pants.backend.scala.bsp.spec import (
    ScalaBuildTarget,
    ScalacOptionsItem,
    ScalacOptionsParams,
    ScalacOptionsResult,
    ScalaMainClassesParams,
    ScalaMainClassesResult,
    ScalaPlatform,
    ScalaTestClassesParams,
    ScalaTestClassesResult,
)
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.target_types import ScalaFieldSet, ScalaSourceField
from pants.base.build_root import BuildRoot
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import BuildTarget, BuildTargetIdentifier, StatusCode
from pants.bsp.spec.targets import DependencyModule
from pants.bsp.util_rules.compile import BSPCompileRequest, BSPCompileResult
from pants.bsp.util_rules.lifecycle import BSPLanguageSupport
from pants.bsp.util_rules.targets import (
    BSPBuildTargetsMetadataRequest,
    BSPBuildTargetsMetadataResult,
    BSPDependencyModulesRequest,
    BSPDependencyModulesResult,
)
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestEntries,
    FileEntry,
    Workspace,
)
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import _uncacheable_rule, collect_rules, rule
from pants.engine.target import (
    CoarsenedTargets,
    FieldSet,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.bsp.spec import MavenDependencyModule, MavenDependencyModuleArtifact
from pants.jvm.compile import (
    ClasspathEntryRequest,
    ClasspathEntryRequestFactory,
    FallibleClasspathEntry,
)
from pants.jvm.resolve.common import ArtifactRequirement, ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import (
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
    ToolClasspath,
    ToolClasspathRequest,
)
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmArtifactFieldSet, JvmResolveField

LANGUAGE_ID = "scala"

_logger = logging.getLogger(__name__)


class ScalaBSPLanguageSupport(BSPLanguageSupport):
    language_id = LANGUAGE_ID
    can_compile = True


@dataclass(frozen=True)
class ScalaMetadataFieldSet(FieldSet):
    required_fields = (ScalaSourceField, JvmResolveField)

    source: ScalaSourceField
    resolve: JvmResolveField


class ScalaBSPBuildTargetsMetadataRequest(BSPBuildTargetsMetadataRequest):
    language_id = LANGUAGE_ID
    can_merge_metadata_from = ("java",)
    field_set_type = ScalaMetadataFieldSet


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
async def bsp_resolve_scala_metadata(
    request: ScalaBSPBuildTargetsMetadataRequest,
    jvm: JvmSubsystem,
    scala: ScalaSubsystem,
    build_root: BuildRoot,
) -> BSPBuildTargetsMetadataResult:
    resolves = {fs.resolve.normalized_value(jvm) for fs in request.field_sets}
    if len(resolves) > 1:
        raise ValueError("Cannot provide Scala metadata for multiple resolves.")
    resolve = list(resolves)[0]
    scala_version = scala.version_for_resolve(resolve)

    scala_runtime = await Get(
        MaterializeScalaRuntimeJarsResult, MaterializeScalaRuntimeJarsRequest(scala_version)
    )

    scala_jar_uris = tuple(
        build_root.pathlib_path.joinpath(".pants.d/bsp").joinpath(p).as_uri()
        for p in scala_runtime.content.files
    )

    return BSPBuildTargetsMetadataResult(
        metadata=ScalaBuildTarget(
            scala_organization="org.scala-lang",
            scala_version=scala_version,
            scala_binary_version=".".join(scala_version.split(".")[0:2]),
            platform=ScalaPlatform.JVM,
            jars=scala_jar_uris,
        ),
        can_compile=True,
        digest=scala_runtime.content.digest,
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


@_uncacheable_rule
async def handle_bsp_scalac_options_request(
    request: HandleScalacOptionsRequest,
    build_root: BuildRoot,
    workspace: Workspace,
) -> HandleScalacOptionsResult:
    targets = await Get(Targets, BuildTargetIdentifier, request.bsp_target_id)
    coarsened_targets = await Get(CoarsenedTargets, Addresses(tgt.address for tgt in targets))
    resolve = await Get(CoursierResolveKey, CoarsenedTargets, coarsened_targets)
    lockfile = await Get(CoursierResolvedLockfile, CoursierResolveKey, resolve)

    resolve_digest = await Get(
        Digest,
        CreateDigest([FileEntry(entry.file_name, entry.file_digest) for entry in lockfile.entries]),
    )

    resolve_digest = await Get(
        Digest, AddPrefix(resolve_digest, f"jvm/resolves/{resolve.name}/lib")
    )

    workspace.write_digest(resolve_digest, path_prefix=".pants.d/bsp")

    classpath = [
        build_root.pathlib_path.joinpath(
            f".pants.d/bsp/jvm/resolves/{resolve.name}/lib/{entry.file_name}"
        ).as_uri()
        for entry in lockfile.entries
    ]

    return HandleScalacOptionsResult(
        ScalacOptionsItem(
            target=request.bsp_target_id,
            options=(),
            classpath=tuple(classpath),
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
# Scala Main Classes Request
# See https://build-server-protocol.github.io/docs/extensions/scala.html#scala-main-classes-request
# -----------------------------------------------------------------------------------------------


class ScalaMainClassesHandlerMapping(BSPHandlerMapping):
    method_name = "buildTarget/scalaMainClasses"
    request_type = ScalaMainClassesParams
    response_type = ScalaMainClassesResult


@rule
async def bsp_scala_main_classes_request(request: ScalaMainClassesParams) -> ScalaMainClassesResult:
    # TODO: This is a stub. VSCode/Metals calls this RPC and expects it to exist.
    return ScalaMainClassesResult(
        items=(),
        origin_id=request.origin_id,
    )


# -----------------------------------------------------------------------------------------------
# Scala Test Classes Request
# See https://build-server-protocol.github.io/docs/extensions/scala.html#scala-test-classes-request
# -----------------------------------------------------------------------------------------------


class ScalaTestClassesHandlerMapping(BSPHandlerMapping):
    method_name = "buildTarget/scalaTestClasses"
    request_type = ScalaTestClassesParams
    response_type = ScalaTestClassesResult


@rule
async def bsp_scala_test_classes_request(request: ScalaTestClassesParams) -> ScalaTestClassesResult:
    # TODO: This is a stub. VSCode/Metals calls this RPC and expects it to exist.
    return ScalaTestClassesResult(
        items=(),
        origin_id=request.origin_id,
    )


# -----------------------------------------------------------------------------------------------
# Dependency Modules
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScalaBSPDependencyModulesRequest(BSPDependencyModulesRequest):
    field_set_type = ScalaMetadataFieldSet


def get_entry_for_coord(
    lockfile: CoursierResolvedLockfile, coord: Coordinate
) -> CoursierLockfileEntry | None:
    for entry in lockfile.entries:
        if entry.coord == coord:
            return entry
    return None


@rule
async def scala_bsp_dependency_modules(
    request: ScalaBSPDependencyModulesRequest,
    build_root: BuildRoot,
) -> BSPDependencyModulesResult:
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses([fs.address for fs in request.field_sets])
    )
    resolve = await Get(CoursierResolveKey, CoarsenedTargets, coarsened_targets)
    lockfile = await Get(CoursierResolvedLockfile, CoursierResolveKey, resolve)

    # TODO: Can this use ClasspathEntryRequest?
    transitive_targets = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest(
            roots=[
                tgt.address
                for coarsened_target in coarsened_targets
                for tgt in coarsened_target.members
            ]
        ),
    )

    artifact_requirements = [
        ArtifactRequirement.from_jvm_artifact_target(tgt)
        for tgt in transitive_targets.closure
        if JvmArtifactFieldSet.is_applicable(tgt)
    ]

    applicable_lockfile_entries: set[CoursierLockfileEntry] = set()
    for artifact_requirement in artifact_requirements:
        entry = get_entry_for_coord(lockfile, artifact_requirement.coordinate)
        if not entry:
            _logger.warning(
                f"No lockfile entry for {artifact_requirement.coordinate} in resolve {resolve.name}."
            )
            continue
        applicable_lockfile_entries.add(entry)

    resolve_digest = await Get(
        Digest,
        CreateDigest(
            [FileEntry(entry.file_name, entry.file_digest) for entry in applicable_lockfile_entries]
        ),
    )

    resolve_digest = await Get(
        Digest, AddPrefix(resolve_digest, f"jvm/resolves/{resolve.name}/lib")
    )

    modules = [
        DependencyModule(
            name=f"{entry.coord.group}:{entry.coord.artifact}",
            version=entry.coord.version,
            data=MavenDependencyModule(
                organization=entry.coord.group,
                name=entry.coord.artifact,
                version=entry.coord.version,
                scope=None,
                artifacts=(
                    MavenDependencyModuleArtifact(
                        uri=build_root.pathlib_path.joinpath(
                            f".pants.d/bsp/jvm/resolves/{resolve.name}/lib/{entry.file_name}"
                        ).as_uri()
                    ),
                ),
            ),
        )
        for entry in applicable_lockfile_entries
    ]

    return BSPDependencyModulesResult(
        modules=tuple(modules),
        digest=resolve_digest,
    )


# -----------------------------------------------------------------------------------------------
# Compile Request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScalaBSPCompileRequest(BSPCompileRequest):
    field_set_type = ScalaFieldSet


@rule
async def bsp_scala_compile_request(
    request: ScalaBSPCompileRequest,
    classpath_entry_request: ClasspathEntryRequestFactory,
) -> BSPCompileResult:
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses([fs.address for fs in request.field_sets])
    )
    resolve = await Get(CoursierResolveKey, CoarsenedTargets, coarsened_targets)

    results = await MultiGet(
        Get(
            FallibleClasspathEntry,
            ClasspathEntryRequest,
            classpath_entry_request.for_targets(component=coarsened_target, resolve=resolve),
        )
        for coarsened_target in coarsened_targets
    )

    status = StatusCode.OK
    if any(r.exit_code != 0 for r in results):
        status = StatusCode.ERROR

    output_digest = EMPTY_DIGEST
    if status == StatusCode.OK:
        output_entries = []
        for result in results:
            if not result.output:
                continue
            entries = await Get(DigestEntries, Digest, result.output.digest)
            output_entries.extend(
                [
                    dataclasses.replace(
                        entry,
                        path=f"jvm/resolves/{resolve.name}/lib/{os.path.basename(entry.path)}",
                    )
                    for entry in entries
                ]
            )
        output_digest = await Get(Digest, CreateDigest(output_entries))

    return BSPCompileResult(
        status=status,
        output_digest=output_digest,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(BSPLanguageSupport, ScalaBSPLanguageSupport),
        UnionRule(BSPBuildTargetsMetadataRequest, ScalaBSPBuildTargetsMetadataRequest),
        UnionRule(BSPHandlerMapping, ScalacOptionsHandlerMapping),
        UnionRule(BSPHandlerMapping, ScalaMainClassesHandlerMapping),
        UnionRule(BSPHandlerMapping, ScalaTestClassesHandlerMapping),
        UnionRule(BSPCompileRequest, ScalaBSPCompileRequest),
        UnionRule(BSPDependencyModulesRequest, ScalaBSPDependencyModulesRequest),
    )
