# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
import pkgutil
from dataclasses import dataclass

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.scala.subsystem import PluginArtifactSpec, ScalaPBSubsystem
from pants.backend.codegen.protobuf.target_types import (
    ProtobufDependenciesField,
    ProtobufSourceField,
)
from pants.backend.scala.target_types import ScalaSourceField
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    FileContent,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.platform import Platform
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    InjectDependenciesRequest,
    InjectedDependencies,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.compile import ClasspathEntry
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirements,
    Coordinate,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)
from pants.jvm.resolve.jvm_tool import (
    GatherJvmCoordinatesRequest,
    JvmToolLockfileRequest,
    JvmToolLockfileSentinel,
)
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet


class GenerateScalaFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSourceField
    output = ScalaSourceField


class ScalapbcToolLockfileSentinel(JvmToolLockfileSentinel):
    options_scope = ScalaPBSubsystem.options_scope


class ScalaPBShimCompiledClassfiles(ClasspathEntry):
    pass


@dataclass(frozen=True)
class MaterializeJvmPluginRequest:
    plugin: PluginArtifactSpec


@dataclass(frozen=True)
class MaterializedJvmPlugin:
    name: str
    classpath: MaterializedClasspath

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
    jdk_setup: JdkSetup,
    bash: BashBinary,
) -> GeneratedSources:
    output_dir = "_generated_files"
    toolcp_relpath = "__toolcp"
    shimcp_relpath = "__shimcp"
    plugins_relpath = "__plugins"
    protoc_relpath = "__protoc"

    (
        downloaded_protoc_binary,
        tool_classpath,
        empty_output_dir,
        transitive_targets,
        inherit_env,
    ) = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, protoc.get_request(Platform.current)),
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                lockfiles=(scalapb.resolved_lockfile(),),
            ),
        ),
        Get(Digest, CreateDigest([Directory(output_dir)])),
        Get(TransitiveTargets, TransitiveTargetsRequest([request.protocol_target.address])),
        # Need PATH so that ScalaPB can invoke `mkfifo`.
        Get(Environment, EnvironmentRequest(requested=["PATH"])),
    )

    # NB: By stripping the source roots, we avoid having to set the value `--proto_path`
    # for Protobuf imports to be discoverable.
    all_sources_stripped, target_sources_stripped = await MultiGet(
        Get(
            StrippedSourceFiles,
            SourceFilesRequest(
                tgt[ProtobufSourceField]
                for tgt in transitive_targets.closure
                if tgt.has_field(ProtobufSourceField)
            ),
        ),
        Get(
            StrippedSourceFiles, SourceFilesRequest([request.protocol_target[ProtobufSourceField]])
        ),
    )

    merged_jvm_plugins_digest = EMPTY_DIGEST
    maybe_jvm_plugins_setup_args: tuple[str, ...] = ()
    maybe_jvm_plugins_output_args: tuple[str, ...] = ()
    jvm_plugins = scalapb.jvm_plugins
    if jvm_plugins:
        materialized_jvm_plugins = await Get(
            MaterializedJvmPlugins, MaterializeJvmPluginsRequest(jvm_plugins)
        )
        merged_jvm_plugins_digest = materialized_jvm_plugins.digest
        maybe_jvm_plugins_setup_args = materialized_jvm_plugins.setup_args(plugins_relpath)
        maybe_jvm_plugins_output_args = tuple(
            f"--{plugin.name}_out={output_dir}" for plugin in materialized_jvm_plugins.plugins
        )

    immutable_input_digests = {
        **jdk_setup.immutable_input_digests,
        toolcp_relpath: tool_classpath.digest,
        shimcp_relpath: shim_classfiles.digest,
        plugins_relpath: merged_jvm_plugins_digest,
        protoc_relpath: downloaded_protoc_binary.digest,
    }

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                all_sources_stripped.snapshot.digest,
                empty_output_dir,
            ]
        ),
    )

    result = await Get(
        ProcessResult,
        Process(
            argv=[
                *jdk_setup.args(
                    bash, [*tool_classpath.classpath_entries(toolcp_relpath), shimcp_relpath]
                ),
                "org.pantsbuild.backend.scala.scalapb.ScalaPBShim",
                f"--protoc={os.path.join(protoc_relpath, downloaded_protoc_binary.exe)}",
                *maybe_jvm_plugins_setup_args,
                f"--scala_out={output_dir}",
                *maybe_jvm_plugins_output_args,
                *target_sources_stripped.snapshot.files,
            ],
            input_digest=input_digest,
            immutable_input_digests=immutable_input_digests,
            use_nailgun=immutable_input_digests,
            description=f"Generating Scala sources from {request.protocol_target.address}.",
            level=LogLevel.DEBUG,
            output_directories=(output_dir,),
            env={**jdk_setup.env, **inherit_env},
            append_only_caches=jdk_setup.append_only_caches,
        ),
    )

    normalized_digest, source_root = await MultiGet(
        Get(Digest, RemovePrefix(result.output_digest, output_dir)),
        Get(SourceRoot, SourceRootRequest, SourceRootRequest.for_target(request.protocol_target)),
    )

    source_root_restored = (
        await Get(Snapshot, AddPrefix(normalized_digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, normalized_digest)
    )
    return GeneratedSources(source_root_restored)


class InjectScalaProtobufDependencies(InjectDependenciesRequest):
    inject_for = ProtobufDependenciesField


@rule
async def inject_scalapb_dependencies(
    _: InjectScalaProtobufDependencies, scalapb: ScalaPBSubsystem
) -> InjectedDependencies:
    addresses = await Get(Addresses, UnparsedAddressInputs, scalapb.runtime_dependencies)
    return InjectedDependencies(addresses)


@rule
async def materialize_jvm_plugin(request: MaterializeJvmPluginRequest) -> MaterializedJvmPlugin:
    requirements = await Get(
        ArtifactRequirements,
        GatherJvmCoordinatesRequest(
            artifact_inputs=FrozenOrderedSet([request.plugin.artifact]),
            option_name="--scalapb-plugin-artifacts",
        ),
    )
    classpath = await Get(
        MaterializedClasspath, MaterializedClasspathRequest(artifact_requirements=(requirements,))
    )
    return MaterializedJvmPlugin(
        name=request.plugin.name,
        classpath=classpath,
    )


@rule
async def materialize_jvm_plugins(request: MaterializeJvmPluginsRequest) -> MaterializedJvmPlugins:
    materialized_plugins = await MultiGet(
        Get(MaterializedJvmPlugin, MaterializeJvmPluginRequest(plugin))
        for plugin in request.plugins
    )
    plugin_digests = await MultiGet(
        Get(Digest, AddPrefix(p.classpath.digest, p.name)) for p in materialized_plugins
    )
    merged_plugins_digest = await Get(Digest, MergeDigests(plugin_digests))
    return MaterializedJvmPlugins(merged_plugins_digest, materialized_plugins)


SHIM_SCALA_VERSION = "2.13.7"


# TODO(13879): Consolidate compilation of wrapper binaries to common rules.
@rule
async def setup_scalapb_shim_classfiles(
    scalapb: ScalaPBSubsystem, jdk_setup: JdkSetup, bash: BashBinary
) -> ScalaPBShimCompiledClassfiles:
    dest_dir = "classfiles"

    scalapb_shim_content = pkgutil.get_data(
        "pants.backend.codegen.protobuf.scala", "ScalaPBShim.scala"
    )
    if not scalapb_shim_content:
        raise AssertionError("Unable to find ScalaParser.scala resource.")

    scalapb_shim_source = FileContent("ScalaPBShim.scala", scalapb_shim_content)

    tool_classpath, shim_classpath, source_digest = await MultiGet(
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                prefix="__toolcp",
                artifact_requirements=(
                    ArtifactRequirements.from_coordinates(
                        [
                            Coordinate(
                                group="org.scala-lang",
                                artifact="scala-compiler",
                                version=SHIM_SCALA_VERSION,
                            ),
                            Coordinate(
                                group="org.scala-lang",
                                artifact="scala-library",
                                version=SHIM_SCALA_VERSION,
                            ),
                            Coordinate(
                                group="org.scala-lang",
                                artifact="scala-reflect",
                                version=SHIM_SCALA_VERSION,
                            ),
                        ]
                    ),
                ),
            ),
        ),
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                prefix="__shimcp",
                lockfiles=(scalapb.resolved_lockfile(),),
            ),
        ),
        Get(
            Digest,
            CreateDigest(
                [
                    scalapb_shim_source,
                    Directory(dest_dir),
                ]
            ),
        ),
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                tool_classpath.digest,
                shim_classpath.digest,
                source_digest,
            )
        ),
    )

    # NB: We do not use nailgun for this process, since it is launched exactly once.
    process_result = await Get(
        ProcessResult,
        Process(
            argv=[
                *jdk_setup.args(bash, tool_classpath.classpath_entries()),
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
            append_only_caches=jdk_setup.append_only_caches,
            immutable_input_digests=jdk_setup.immutable_input_digests,
            env=jdk_setup.env,
            output_directories=(dest_dir,),
            description="Compile ScalaPB shim with scalac",
            level=LogLevel.DEBUG,
        ),
    )
    stripped_classfiles_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, dest_dir)
    )
    return ScalaPBShimCompiledClassfiles(digest=stripped_classfiles_digest)


@rule
async def generate_scalapbc_lockfile_request(
    _: ScalapbcToolLockfileSentinel,
    tool: ScalaPBSubsystem,
) -> JvmToolLockfileRequest:
    return JvmToolLockfileRequest.from_tool(tool)


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateScalaFromProtobufRequest),
        UnionRule(JvmToolLockfileSentinel, ScalapbcToolLockfileSentinel),
    ]
