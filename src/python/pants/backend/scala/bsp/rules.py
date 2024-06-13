# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
from pants.backend.scala.compile.scalac_plugins import (
    ScalaPlugins,
    ScalaPluginsForTargetRequest,
    ScalaPluginsRequest,
    ScalaPluginTargetsForTarget,
)
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import ScalaFieldSet, ScalaSourceField
from pants.backend.scala.util_rules.versions import (
    ScalaArtifactsForVersionRequest,
    ScalaArtifactsForVersionResult,
    ScalaVersion,
)
from pants.base.build_root import BuildRoot
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import BuildTargetIdentifier
from pants.bsp.spec.targets import DependencyModule
from pants.bsp.util_rules.lifecycle import BSPLanguageSupport
from pants.bsp.util_rules.targets import (
    BSPBuildTargetsMetadataRequest,
    BSPBuildTargetsMetadataResult,
    BSPCompileRequest,
    BSPCompileResult,
    BSPDependencyModulesRequest,
    BSPDependencyModulesResult,
    BSPResourcesRequest,
    BSPResourcesResult,
)
from pants.core.util_rules.system_binaries import BashBinary, ReadlinkBinary
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, CreateDigest, Digest, FileContent, MergeDigests, Workspace
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import _uncacheable_rule, collect_rules, rule
from pants.engine.target import CoarsenedTarget, CoarsenedTargets, FieldSet, Targets
from pants.engine.unions import UnionRule
from pants.jvm.bsp.compile import _jvm_bsp_compile, jvm_classes_directory
from pants.jvm.bsp.compile import rules as jvm_compile_rules
from pants.jvm.bsp.resources import _jvm_bsp_resources
from pants.jvm.bsp.resources import rules as jvm_resources_rules
from pants.jvm.bsp.spec import JvmBuildTarget, MavenDependencyModule, MavenDependencyModuleArtifact
from pants.jvm.compile import ClasspathEntry, ClasspathEntryRequest, ClasspathEntryRequestFactory
from pants.jvm.jdk_rules import DefaultJdk, JdkEnvironment, JdkRequest
from pants.jvm.resolve.common import ArtifactRequirement, ArtifactRequirements
from pants.jvm.resolve.coordinate import Coordinate
from pants.jvm.resolve.coursier_fetch import (
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
    ToolClasspath,
    ToolClasspathRequest,
)
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmArtifactFieldSet, JvmJdkField, JvmResolveField
from pants.util.logging import LogLevel

LANGUAGE_ID = "scala"

_logger = logging.getLogger(__name__)


class ScalaBSPLanguageSupport(BSPLanguageSupport):
    language_id = LANGUAGE_ID
    can_compile = True
    can_provide_resources = True


@dataclass(frozen=True)
class ScalaMetadataFieldSet(FieldSet):
    required_fields = (ScalaSourceField, JvmResolveField, JvmJdkField)

    source: ScalaSourceField
    resolve: JvmResolveField
    jdk: JvmJdkField


class ScalaBSPBuildTargetsMetadataRequest(BSPBuildTargetsMetadataRequest):
    language_id = LANGUAGE_ID
    can_merge_metadata_from = ("java",)
    field_set_type = ScalaMetadataFieldSet

    resolve_prefix = "jvm"
    resolve_field = JvmResolveField


@dataclass(frozen=True)
class ThirdpartyModulesRequest:
    addresses: Addresses


@dataclass(frozen=True)
class ThirdpartyModules:
    resolve: CoursierResolveKey
    entries: dict[CoursierLockfileEntry, ClasspathEntry]
    merged_digest: Digest


@rule
async def collect_thirdparty_modules(
    request: ThirdpartyModulesRequest,
    classpath_entry_request: ClasspathEntryRequestFactory,
) -> ThirdpartyModules:
    coarsened_targets = await Get(CoarsenedTargets, Addresses, request.addresses)
    resolve = await Get(CoursierResolveKey, CoarsenedTargets, coarsened_targets)
    lockfile = await Get(CoursierResolvedLockfile, CoursierResolveKey, resolve)

    applicable_lockfile_entries: dict[CoursierLockfileEntry, CoarsenedTarget] = {}
    for ct in coarsened_targets.coarsened_closure():
        for tgt in ct.members:
            if not JvmArtifactFieldSet.is_applicable(tgt):
                continue

            artifact_requirement = ArtifactRequirement.from_jvm_artifact_target(tgt)
            entry = get_entry_for_coord(lockfile, artifact_requirement.coordinate)
            if not entry:
                _logger.warning(
                    f"No lockfile entry for {artifact_requirement.coordinate} in resolve {resolve.name}."
                )
                continue
            applicable_lockfile_entries[entry] = ct

    classpath_entries = await MultiGet(
        Get(
            ClasspathEntry,
            ClasspathEntryRequest,
            classpath_entry_request.for_targets(component=target, resolve=resolve),
        )
        for target in applicable_lockfile_entries.values()
    )

    resolve_digest = await Get(Digest, MergeDigests(cpe.digest for cpe in classpath_entries))

    return ThirdpartyModules(
        resolve,
        dict(zip(applicable_lockfile_entries, classpath_entries)),
        resolve_digest,
    )


async def _materialize_scala_runtime_jars(scala_version: ScalaVersion) -> Snapshot:
    scala_artifacts = await Get(
        ScalaArtifactsForVersionResult, ScalaArtifactsForVersionRequest(scala_version)
    )

    tool_classpath = await Get(
        ToolClasspath,
        ToolClasspathRequest(
            artifact_requirements=ArtifactRequirements.from_coordinates(
                scala_artifacts.all_coordinates
            ),
        ),
    )

    return await Get(
        Snapshot,
        AddPrefix(tool_classpath.content.digest, f"jvm/scala-runtime/{scala_version}"),
    )


@rule
async def bsp_resolve_scala_metadata(
    request: ScalaBSPBuildTargetsMetadataRequest,
    bash: BashBinary,
    jvm: JvmSubsystem,
    scala: ScalaSubsystem,
    build_root: BuildRoot,
    readlink: ReadlinkBinary,
) -> BSPBuildTargetsMetadataResult:
    resolves = {fs.resolve.normalized_value(jvm) for fs in request.field_sets}
    jdk_versions = {fs.jdk for fs in request.field_sets}
    if len(resolves) > 1:
        raise ValueError(
            "Cannot provide Scala metadata for multiple resolves. Please set the "
            "`resolve = jvm:$resolve` field in your `[experimental-bsp].groups_config_files` to "
            "select the relevant resolve to use."
        )
    (resolve,) = resolves

    scala_version = scala.version_for_resolve(resolve)
    scala_runtime = await _materialize_scala_runtime_jars(scala_version)

    #
    # Extract the JDK paths from an lawful-evil process so we can supply it to the IDE.
    #
    # Why lawful-evil?
    # This script relies on implementation details of the Pants JVM execution environment,
    # namely that the Coursier Archive Cache (i.e. where JDKs are extracted to after download)
    # is stored into a predictable location on disk and symlinked into the sandbox on process
    # startup. The script reads the symlink of the cache directory, and outputs the linked
    # location of the JDK (according to Coursier), and we use that to calculate the permanent
    # location of the JDK.
    #
    # Please don't do anything like this except as a last resort.
    #

    # The maximum JDK version will be compatible with all the specified targets
    jdk_requests = [JdkRequest.from_field(version) for version in jdk_versions]
    jdk_request = max(jdk_requests, key=_jdk_request_sort_key(jvm))
    jdk = await Get(JdkEnvironment, JdkRequest, jdk_request)

    if any(i.version == DefaultJdk.SYSTEM for i in jdk_requests):
        system_jdk = await Get(JdkEnvironment, JdkRequest, JdkRequest.SYSTEM)
        if system_jdk.jre_major_version > jdk.jre_major_version:
            jdk = system_jdk

    cmd = "leak_paths.sh"
    leak_jdk_sandbox_paths = textwrap.dedent(  # noqa: PNT20
        f"""\
        # Script to leak JDK cache paths out of Coursier sandbox so that BSP can use them.

        {readlink.path} {jdk.coursier.cache_dir}
        {jdk.java_home_command}
        """
    )
    leak_sandbox_path_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    cmd,
                    leak_jdk_sandbox_paths.encode("utf-8"),
                    is_executable=True,
                ),
            ]
        ),
    )

    leaked_paths = await Get(
        ProcessResult,
        Process(
            [
                bash.path,
                cmd,
            ],
            input_digest=leak_sandbox_path_digest,
            immutable_input_digests=jdk.immutable_input_digests,
            env=jdk.env,
            use_nailgun=(),
            description="Report JDK cache paths for BSP",
            append_only_caches=jdk.append_only_caches,
            level=LogLevel.TRACE,
        ),
    )

    cache_dir, jdk_home = leaked_paths.stdout.decode().strip().split("\n")

    _, sep, suffix = jdk_home.partition(jdk.coursier.cache_dir)
    if sep:
        coursier_java_home = cache_dir + suffix
    else:
        # Partition failed. Probably a system JDK instead
        coursier_java_home = jdk_home

    scala_jar_uris = tuple(
        # TODO: Why is this hardcoded and not under pants_workdir?
        build_root.pathlib_path.joinpath(".pants.d", "bsp", p).as_uri()
        for p in scala_runtime.files
    )

    jvm_build_target = JvmBuildTarget(
        java_home=Path(coursier_java_home).as_uri(),
        java_version=f"1.{jdk.jre_major_version}",
    )

    return BSPBuildTargetsMetadataResult(
        metadata=ScalaBuildTarget(
            scala_organization="org.scala-lang",
            scala_version=str(scala_version),
            scala_binary_version=scala_version.binary,
            platform=ScalaPlatform.JVM,
            jars=scala_jar_uris,
            jvm_build_target=jvm_build_target,
        ),
        digest=scala_runtime.digest,
    )


def _jdk_request_sort_key(
    jvm: JvmSubsystem,
) -> Callable[
    [
        JdkRequest,
    ],
    tuple[int, ...],
]:
    def sort_key_function(request: JdkRequest) -> tuple[int, ...]:
        if request == JdkRequest.SYSTEM:
            return (-1,)

        version_str = request.version if isinstance(request.version, str) else jvm.jdk
        _, version = version_str.split(":")

        return tuple(int(i) for i in version.split("."))

    return sort_key_function


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
    request: HandleScalacOptionsRequest, build_root: BuildRoot, workspace: Workspace, scalac: Scalac
) -> HandleScalacOptionsResult:
    targets = await Get(Targets, BuildTargetIdentifier, request.bsp_target_id)
    thirdparty_modules = await Get(
        ThirdpartyModules, ThirdpartyModulesRequest(Addresses(tgt.address for tgt in targets))
    )
    resolve = thirdparty_modules.resolve

    scalac_plugin_targets = await MultiGet(
        Get(ScalaPluginTargetsForTarget, ScalaPluginsForTargetRequest(tgt, resolve.name))
        for tgt in targets
    )

    local_plugins_prefix = f"jvm/resolves/{resolve.name}/plugins"
    local_plugins = await Get(
        ScalaPlugins, ScalaPluginsRequest.from_target_plugins(scalac_plugin_targets, resolve)
    )

    thirdparty_modules_prefix = f"jvm/resolves/{resolve.name}/lib"
    thirdparty_modules_digest, local_plugins_digest = await MultiGet(
        Get(Digest, AddPrefix(thirdparty_modules.merged_digest, thirdparty_modules_prefix)),
        Get(Digest, AddPrefix(local_plugins.classpath.digest, local_plugins_prefix)),
    )

    resolve_digest = await Get(
        Digest, MergeDigests([thirdparty_modules_digest, local_plugins_digest])
    )
    workspace.write_digest(resolve_digest, path_prefix=".pants.d/bsp")

    classpath = tuple(
        build_root.pathlib_path.joinpath(
            f".pants.d/bsp/{thirdparty_modules_prefix}/{filename}"
        ).as_uri()
        for cp_entry in thirdparty_modules.entries.values()
        for filename in cp_entry.filenames
    )

    return HandleScalacOptionsResult(
        ScalacOptionsItem(
            target=request.bsp_target_id,
            options=(*local_plugins.args(local_plugins_prefix), *scalac.args),
            classpath=classpath,
            class_directory=build_root.pathlib_path.joinpath(
                f".pants.d/bsp/{jvm_classes_directory(request.bsp_target_id)}"
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
    thirdparty_modules = await Get(
        ThirdpartyModules,
        ThirdpartyModulesRequest(Addresses(fs.address for fs in request.field_sets)),
    )
    resolve = thirdparty_modules.resolve

    resolve_digest = await Get(
        Digest, AddPrefix(thirdparty_modules.merged_digest, f"jvm/resolves/{resolve.name}/lib")
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
                artifacts=tuple(
                    MavenDependencyModuleArtifact(
                        uri=build_root.pathlib_path.joinpath(
                            f".pants.d/bsp/jvm/resolves/{resolve.name}/lib/{filename}"
                        ).as_uri()
                    )
                    for filename in cp_entry.filenames
                ),
            ),
        )
        for entry, cp_entry in thirdparty_modules.entries.items()
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
    result: BSPCompileResult = await _jvm_bsp_compile(request, classpath_entry_request)
    return result


# -----------------------------------------------------------------------------------------------
# Resources Request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScalaBSPResourcesRequest(BSPResourcesRequest):
    field_set_type = ScalaFieldSet


@rule
async def bsp_scala_resources_request(
    request: ScalaBSPResourcesRequest,
    build_root: BuildRoot,
) -> BSPResourcesResult:
    result: BSPResourcesResult = await _jvm_bsp_resources(request, build_root)
    return result


def rules():
    return (
        *collect_rules(),
        *jvm_compile_rules(),
        *jvm_resources_rules(),
        UnionRule(BSPLanguageSupport, ScalaBSPLanguageSupport),
        UnionRule(BSPBuildTargetsMetadataRequest, ScalaBSPBuildTargetsMetadataRequest),
        UnionRule(BSPHandlerMapping, ScalacOptionsHandlerMapping),
        UnionRule(BSPHandlerMapping, ScalaMainClassesHandlerMapping),
        UnionRule(BSPHandlerMapping, ScalaTestClassesHandlerMapping),
        UnionRule(BSPCompileRequest, ScalaBSPCompileRequest),
        UnionRule(BSPResourcesRequest, ScalaBSPResourcesRequest),
        UnionRule(BSPDependencyModulesRequest, ScalaBSPDependencyModulesRequest),
    )
