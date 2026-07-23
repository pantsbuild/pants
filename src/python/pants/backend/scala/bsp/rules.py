# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
    ScalaPluginsForTargetRequest,
    ScalaPluginsRequest,
    fetch_plugins,
    resolve_scala_plugins_for_target,
)
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import ScalaFieldSet, ScalaSourceField
from pants.backend.scala.util_rules.versions import (
    ScalaArtifactsForVersionRequest,
    ScalaVersion,
    resolve_scala_artifacts_for_version,
)
from pants.base.build_root import BuildRoot
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import BuildTargetIdentifier
from pants.bsp.util_rules.lifecycle import BSPLanguageSupport
from pants.bsp.util_rules.queries import compute_handler_query_rules
from pants.bsp.util_rules.targets import (
    BSPBuildTargetsMetadataRequest,
    BSPBuildTargetsMetadataResult,
    BSPCompileRequest,
    BSPCompileResult,
    BSPDependencyModulesRequest,
    BSPDependencyModulesResult,
    BSPDependencySourcesRequest,
    BSPDependencySourcesResult,
    BSPResourcesRequest,
    BSPResourcesResult,
    resolve_bsp_build_target_addresses,
)
from pants.core.util_rules.system_binaries import BashBinary, ReadlinkBinary
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, CreateDigest, FileContent, MergeDigests, Workspace
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import (
    add_prefix,
    create_digest,
    digest_to_snapshot,
    merge_digests,
)
from pants.engine.process import Process, execute_process_or_raise
from pants.engine.rules import _uncacheable_rule, collect_rules, implicitly, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.jvm.bsp.compile import _jvm_bsp_compile, jvm_classes_directory
from pants.jvm.bsp.compile import rules as jvm_compile_rules
from pants.jvm.bsp.dependencies import (
    ThirdpartyModulesRequest,
    _jvm_bsp_dependency_modules,
    _jvm_bsp_dependency_sources,
    collect_thirdparty_modules,
)
from pants.jvm.bsp.dependencies import rules as jvm_dependencies_rules
from pants.jvm.bsp.resources import _jvm_bsp_resources
from pants.jvm.bsp.resources import rules as jvm_resources_rules
from pants.jvm.bsp.spec import JvmBuildTarget
from pants.jvm.compile import ClasspathEntryRequestFactory
from pants.jvm.jdk_rules import DefaultJdk, JdkRequest, prepare_jdk_environment
from pants.jvm.resolve.common import ArtifactRequirements
from pants.jvm.resolve.coursier_fetch import (
    ToolClasspathRequest,
    materialize_classpath_for_tool,
)
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmJdkField, JvmResolveField
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


async def _materialize_scala_runtime_jars(scala_version: ScalaVersion) -> Snapshot:
    scala_artifacts = await resolve_scala_artifacts_for_version(
        ScalaArtifactsForVersionRequest(scala_version)
    )

    tool_classpath = await materialize_classpath_for_tool(
        ToolClasspathRequest(
            artifact_requirements=ArtifactRequirements.from_coordinates(
                scala_artifacts.all_coordinates
            ),
        ),
    )

    return await digest_to_snapshot(
        **implicitly(AddPrefix(tool_classpath.content.digest, f"jvm/scala-runtime/{scala_version}"))
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
    jdk = await prepare_jdk_environment(**implicitly({jdk_request: JdkRequest}))

    if any(i.version == DefaultJdk.SYSTEM for i in jdk_requests):
        system_jdk = await prepare_jdk_environment(**implicitly({JdkRequest.SYSTEM: JdkRequest}))
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
    leak_sandbox_path_digest = await create_digest(
        CreateDigest(
            [
                FileContent(
                    cmd,
                    leak_jdk_sandbox_paths.encode("utf-8"),
                    is_executable=True,
                ),
            ]
        )
    )

    leaked_paths = await execute_process_or_raise(
        **implicitly(
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
            )
        )
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
        # `jvm.jdk` can be `"system"` (or a user-supplied bare label) instead
        # of the conventional `vendor:version`. Treat that the same as
        # JdkRequest.SYSTEM here so workspace metadata setup doesn't crash.
        if ":" not in version_str:
            return (-1,)
        _, version = version_str.split(":", 1)

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
    targets = await resolve_bsp_build_target_addresses(**implicitly(request.bsp_target_id))
    thirdparty_modules = await collect_thirdparty_modules(
        ThirdpartyModulesRequest(Addresses(tgt.address for tgt in targets)), **implicitly()
    )
    resolve = thirdparty_modules.resolve

    scalac_plugin_targets = await concurrently(
        resolve_scala_plugins_for_target(
            ScalaPluginsForTargetRequest(tgt, resolve.name), **implicitly()
        )
        for tgt in targets
    )

    local_plugins_prefix = f"jvm/resolves/{resolve.name}/plugins"
    local_plugins = await fetch_plugins(
        ScalaPluginsRequest.from_target_plugins(scalac_plugin_targets, resolve)
    )

    thirdparty_modules_prefix = f"jvm/resolves/{resolve.name}/lib"
    thirdparty_modules_digest, local_plugins_digest = await concurrently(
        add_prefix(AddPrefix(thirdparty_modules.merged_digest, thirdparty_modules_prefix)),
        add_prefix(AddPrefix(local_plugins.classpath.digest, local_plugins_prefix)),
    )

    resolve_digest = await merge_digests(
        MergeDigests([thirdparty_modules_digest, local_plugins_digest])
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
            options=(
                # The plugin jars are materialized under `.pants.d/bsp` in the workspace (see
                # the `write_digest` above), so emit absolute paths for BSP clients rather than
                # the digest-relative prefix.
                *local_plugins.args(
                    str(build_root.pathlib_path.joinpath(f".pants.d/bsp/{local_plugins_prefix}"))
                ),
                *scalac.parsed_args_for_resolve(resolve.name),
            ),
            classpath=classpath,
            class_directory=build_root.pathlib_path.joinpath(
                f".pants.d/bsp/{jvm_classes_directory(request.bsp_target_id)}"
            ).as_uri(),
        )
    )


@rule
async def bsp_scalac_options_request(request: ScalacOptionsParams) -> ScalacOptionsResult:
    results = await concurrently(
        handle_bsp_scalac_options_request(HandleScalacOptionsRequest(btgt), **implicitly())
        for btgt in request.targets
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
# Dependency Modules / Sources
# -----------------------------------------------------------------------------------------------
# The bodies live in `pants.jvm.bsp.dependencies` so that any JVM language
# backend (Java, Scala, ...) can register a `BSPDependencyModulesRequest` /
# `BSPDependencySourcesRequest` union member that delegates here.=


@dataclass(frozen=True)
class ScalaBSPDependencyModulesRequest(BSPDependencyModulesRequest):
    field_set_type = ScalaMetadataFieldSet


@rule
async def scala_bsp_dependency_modules(
    request: ScalaBSPDependencyModulesRequest,
    build_root: BuildRoot,
) -> BSPDependencyModulesResult:
    return await _jvm_bsp_dependency_modules(request, build_root)


@dataclass(frozen=True)
class ScalaBSPDependencySourcesRequest(BSPDependencySourcesRequest):
    field_set_type = ScalaMetadataFieldSet


@rule
async def scala_bsp_dependency_sources(
    request: ScalaBSPDependencySourcesRequest,
    build_root: BuildRoot,
) -> BSPDependencySourcesResult:
    return await _jvm_bsp_dependency_sources(request, build_root)


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
    return await _jvm_bsp_compile(request, classpath_entry_request)


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
    base_rules = (
        *collect_rules(),
        *jvm_compile_rules(),
        *jvm_dependencies_rules(),
        *jvm_resources_rules(),
        UnionRule(BSPLanguageSupport, ScalaBSPLanguageSupport),
        UnionRule(BSPBuildTargetsMetadataRequest, ScalaBSPBuildTargetsMetadataRequest),
        UnionRule(BSPHandlerMapping, ScalacOptionsHandlerMapping),
        UnionRule(BSPHandlerMapping, ScalaMainClassesHandlerMapping),
        UnionRule(BSPHandlerMapping, ScalaTestClassesHandlerMapping),
        UnionRule(BSPCompileRequest, ScalaBSPCompileRequest),
        UnionRule(BSPResourcesRequest, ScalaBSPResourcesRequest),
        UnionRule(BSPDependencyModulesRequest, ScalaBSPDependencyModulesRequest),
        UnionRule(BSPDependencySourcesRequest, ScalaBSPDependencySourcesRequest),
    )
    return (*base_rules, *compute_handler_query_rules(base_rules))
