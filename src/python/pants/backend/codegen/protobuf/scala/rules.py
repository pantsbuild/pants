# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from dataclasses import dataclass

from pants.backend.codegen.protobuf import protoc
from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.scala import dependency_inference, symbol_mapper
from pants.backend.codegen.protobuf.scala.subsystem import PluginArtifactSpec, ScalaPBSubsystem
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.backend.scala.target_types import ScalaSourceField
from pants.backend.scala.util_rules.versions import (
    ScalaArtifactsForVersionRequest,
    ScalaVersion,
    resolve_scala_artifacts_for_version,
)
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules import distdir
from pants.core.util_rules.external_tool import download_external_tool
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import strip_source_roots
from pants.engine.env_vars import EnvironmentVarsRequest
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    FileContent,
    MergeDigests,
    RemovePrefix,
)
from pants.engine.internals.graph import transitive_targets
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.internals.platform_rules import environment_vars_subset
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import (
    add_prefix,
    create_digest,
    digest_to_snapshot,
    merge_digests,
    remove_prefix,
)
from pants.engine.platform import Platform
from pants.engine.process import fallible_to_exec_result_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.jvm.compile import ClasspathEntry
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.goals import lockfile
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.common import ArtifactRequirements, GatherJvmCoordinatesRequest
from pants.jvm.resolve.coursier_fetch import (
    ToolClasspath,
    ToolClasspathRequest,
    materialize_classpath_for_tool,
)
from pants.jvm.resolve.jvm_tool import (
    GenerateJvmLockfileFromTool,
    gather_coordinates_for_jvm_lockfile,
)
from pants.jvm.target_types import PrefixedJvmJdkField, PrefixedJvmResolveField
from pants.source.source_root import SourceRootRequest, get_source_root
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.resources import read_resource


class GenerateScalaFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSourceField
    output = ScalaSourceField


class ScalaPBShimCompiledClassfiles(ClasspathEntry):
    pass


@dataclass(frozen=True)
class MaterializeJvmPluginRequest:
    plugin: PluginArtifactSpec


@dataclass(frozen=True)
class MaterializedJvmPlugin:
    name: str
    classpath: ToolClasspath

    def setup_arg(self, plugin_relpath: str) -> str:
        classpath_arg = ":".join(self.classpath.classpath_entries(plugin_relpath))
        return f"--jvm-plugin={self.name}={classpath_arg}"


@dataclass(frozen=True)
class MaterializeJvmPluginsRequest:
    plugins: tuple[PluginArtifactSpec, ...]


@dataclass(frozen=True)
class MaterializedJvmPlugins:
    digest: Digest
    plugins: tuple[MaterializedJvmPlugin, ...]

    def setup_args(self, plugins_relpath: str) -> tuple[str, ...]:
        return tuple(p.setup_arg(os.path.join(plugins_relpath, p.name)) for p in self.plugins)


@rule(desc="Generate Scala from Protobuf", level=LogLevel.DEBUG)
async def generate_scala_from_protobuf(
    request: GenerateScalaFromProtobufRequest,
    protoc: Protoc,
    scalapb: ScalaPBSubsystem,
    shim_classfiles: ScalaPBShimCompiledClassfiles,
    jdk: InternalJdk,
    platform: Platform,
) -> GeneratedSources:
    output_dir = "_generated_files"
    toolcp_relpath = "__toolcp"
    shimcp_relpath = "__shimcp"
    plugins_relpath = "__plugins"
    protoc_relpath = "__protoc"

    lockfile_request = GenerateJvmLockfileFromTool.create(scalapb)
    (
        downloaded_protoc_binary,
        tool_classpath,
        empty_output_dir,
        transitive_targets_for_protobuf_source,
        inherit_env,
    ) = await concurrently(
        download_external_tool(protoc.get_request(platform)),
        materialize_classpath_for_tool(ToolClasspathRequest(lockfile=lockfile_request)),
        create_digest(CreateDigest([Directory(output_dir)])),
        transitive_targets(
            TransitiveTargetsRequest([request.protocol_target.address]), **implicitly()
        ),
        # Need PATH so that ScalaPB can invoke `mkfifo`.
        environment_vars_subset(EnvironmentVarsRequest(requested=["PATH"]), **implicitly()),
    )

    # NB: By stripping the source roots, we avoid having to set the value `--proto_path`
    # for Protobuf imports to be discoverable.
    all_sources_stripped, target_sources_stripped = await concurrently(
        strip_source_roots(
            **implicitly(
                SourceFilesRequest(
                    tgt[ProtobufSourceField]
                    for tgt in transitive_targets_for_protobuf_source.closure
                    if tgt.has_field(ProtobufSourceField)
                )
            )
        ),
        strip_source_roots(
            **implicitly(SourceFilesRequest([request.protocol_target[ProtobufSourceField]]))
        ),
    )

    merged_jvm_plugins_digest = EMPTY_DIGEST
    maybe_jvm_plugins_setup_args: tuple[str, ...] = ()
    maybe_jvm_plugins_output_args: tuple[str, ...] = ()
    jvm_plugins = scalapb.jvm_plugins
    if jvm_plugins:
        materialized_jvm_plugins = await materialize_jvm_plugins(
            MaterializeJvmPluginsRequest(jvm_plugins)
        )
        merged_jvm_plugins_digest = materialized_jvm_plugins.digest
        maybe_jvm_plugins_setup_args = materialized_jvm_plugins.setup_args(plugins_relpath)
        maybe_jvm_plugins_output_args = tuple(
            f"--{plugin.name}_out={output_dir}" for plugin in materialized_jvm_plugins.plugins
        )

    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
        shimcp_relpath: shim_classfiles.digest,
        plugins_relpath: merged_jvm_plugins_digest,
        protoc_relpath: downloaded_protoc_binary.digest,
    }

    input_digest = await merge_digests(
        MergeDigests([all_sources_stripped.snapshot.digest, empty_output_dir])
    )

    result = await fallible_to_exec_result_or_raise(
        **implicitly(
            JvmProcess(
                jdk=jdk,
                classpath_entries=[
                    *tool_classpath.classpath_entries(toolcp_relpath),
                    shimcp_relpath,
                ],
                argv=[
                    "org.pantsbuild.backend.scala.scalapb.ScalaPBShim",
                    f"--protoc={os.path.join(protoc_relpath, downloaded_protoc_binary.exe)}",
                    *maybe_jvm_plugins_setup_args,
                    f"--scala_out={output_dir}",
                    *maybe_jvm_plugins_output_args,
                    *target_sources_stripped.snapshot.files,
                ],
                input_digest=input_digest,
                extra_immutable_input_digests=extra_immutable_input_digests,
                extra_nailgun_keys=extra_immutable_input_digests,
                description=f"Generating Scala sources from {request.protocol_target.address}.",
                level=LogLevel.DEBUG,
                output_directories=(output_dir,),
                extra_env=inherit_env,
            )
        )
    )

    normalized_digest, source_root = await concurrently(
        remove_prefix(RemovePrefix(result.output_digest, output_dir)),
        get_source_root(SourceRootRequest.for_target(request.protocol_target)),
    )

    source_root_restored = (
        await digest_to_snapshot(**implicitly(AddPrefix(normalized_digest, source_root.path)))
        if source_root.path != "."
        else await digest_to_snapshot(normalized_digest)
    )
    return GeneratedSources(source_root_restored)


@rule
async def materialize_jvm_plugin(request: MaterializeJvmPluginRequest) -> MaterializedJvmPlugin:
    requirements = await gather_coordinates_for_jvm_lockfile(
        GatherJvmCoordinatesRequest(
            artifact_inputs=FrozenOrderedSet([request.plugin.artifact]),
            option_name="[scalapb].jvm_plugins",
        )
    )
    classpath = await materialize_classpath_for_tool(
        ToolClasspathRequest(artifact_requirements=requirements)
    )
    return MaterializedJvmPlugin(name=request.plugin.name, classpath=classpath)


@rule
async def materialize_jvm_plugins(
    request: MaterializeJvmPluginsRequest,
) -> MaterializedJvmPlugins:
    materialized_plugins = await concurrently(
        materialize_jvm_plugin(MaterializeJvmPluginRequest(plugin)) for plugin in request.plugins
    )
    plugin_digests = await concurrently(
        add_prefix(AddPrefix(p.classpath.digest, p.name)) for p in materialized_plugins
    )
    merged_plugins_digest = await merge_digests(MergeDigests(plugin_digests))
    return MaterializedJvmPlugins(merged_plugins_digest, materialized_plugins)


SHIM_SCALA_VERSION = ScalaVersion.parse("2.13.7")


# TODO(13879): Consolidate compilation of wrapper binaries to common rules.
@rule
async def setup_scalapb_shim_classfiles(
    scalapb: ScalaPBSubsystem,
    jdk: InternalJdk,
) -> ScalaPBShimCompiledClassfiles:
    dest_dir = "classfiles"

    scalapb_shim_content = read_resource(
        "pants.backend.codegen.protobuf.scala", "ScalaPBShim.scala"
    )
    if not scalapb_shim_content:
        raise AssertionError("Unable to find ScalaParser.scala resource.")

    scalapb_shim_source = FileContent("ScalaPBShim.scala", scalapb_shim_content)

    lockfile_request = GenerateJvmLockfileFromTool.create(scalapb)
    scala_artifacts = await resolve_scala_artifacts_for_version(
        ScalaArtifactsForVersionRequest(SHIM_SCALA_VERSION)
    )
    tool_classpath, shim_classpath, source_digest = await concurrently(
        materialize_classpath_for_tool(
            ToolClasspathRequest(
                prefix="__toolcp",
                artifact_requirements=ArtifactRequirements.from_coordinates(
                    scala_artifacts.all_coordinates
                ),
            )
        ),
        materialize_classpath_for_tool(
            ToolClasspathRequest(prefix="__shimcp", lockfile=lockfile_request)
        ),
        create_digest(CreateDigest([scalapb_shim_source, Directory(dest_dir)])),
    )

    merged_digest = await merge_digests(
        MergeDigests((tool_classpath.digest, shim_classpath.digest, source_digest))
    )

    process_result = await fallible_to_exec_result_or_raise(
        **implicitly(
            JvmProcess(
                jdk=jdk,
                classpath_entries=tool_classpath.classpath_entries(),
                argv=[
                    "scala.tools.nsc.Main",
                    "-bootclasspath",
                    ":".join(tool_classpath.classpath_entries()),
                    "-classpath",
                    ":".join(shim_classpath.classpath_entries()),
                    "-d",
                    dest_dir,
                    scalapb_shim_source.path,
                ],
                input_digest=merged_digest,
                extra_jvm_options=scalapb.jvm_options,
                output_directories=(dest_dir,),
                description="Compile ScalaPB shim with scalac",
                level=LogLevel.DEBUG,
                # NB: We do not use nailgun for this process, since it is launched exactly once.
                use_nailgun=False,
            )
        )
    )
    stripped_classfiles_digest = await remove_prefix(
        RemovePrefix(process_result.output_digest, dest_dir)
    )
    return ScalaPBShimCompiledClassfiles(digest=stripped_classfiles_digest)


def rules():
    return [
        *collect_rules(),
        *lockfile.rules(),
        *dependency_inference.rules(),
        *symbol_mapper.rules(),
        UnionRule(GenerateSourcesRequest, GenerateScalaFromProtobufRequest),
        UnionRule(ExportableTool, ScalaPBSubsystem),
        *protoc.rules(),
        ProtobufSourceTarget.register_plugin_field(PrefixedJvmJdkField),
        ProtobufSourcesGeneratorTarget.register_plugin_field(PrefixedJvmJdkField),
        ProtobufSourceTarget.register_plugin_field(PrefixedJvmResolveField),
        ProtobufSourcesGeneratorTarget.register_plugin_field(PrefixedJvmResolveField),
        # Rules to avoid rule graph errors.
        *artifact_mapper.rules(),
        *distdir.rules(),
    ]
