# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain

from pants.backend.java.target_types import JavaFieldSet, JavaGeneratorFieldSet, JavaSourceField
from pants.backend.scala.compile.scalac_plugins import (
    ScalaPluginsForTargetRequest,
    ScalaPluginsRequest,
    fetch_plugins,
    resolve_scala_plugins_for_target,
)
from pants.backend.scala.compile.scalac_plugins import rules as scalac_plugins_rules
from pants.backend.scala.resolve.artifact import rules as scala_artifact_rules
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import ScalaFieldSet, ScalaGeneratorFieldSet, ScalaSourceField
from pants.backend.scala.util_rules import versions
from pants.backend.scala.util_rules.versions import (
    ScalaArtifactsForVersionRequest,
    ScalaVersion,
    resolve_scala_artifacts_for_version,
)
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import strip_source_roots
from pants.core.util_rules.system_binaries import BashBinary, ZipBinary
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Directory, MergeDigests
from pants.engine.intrinsics import create_digest, execute_process, merge_digests
from pants.engine.process import Process, ProcessCacheScope, execute_process_or_raise
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import CoarsenedTarget, SourcesField
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.compile import (
    ClasspathDependenciesRequest,
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntry,
    compile_classpath_entries,
)
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import JdkRequest, JvmProcess, prepare_jdk_environment
from pants.jvm.resolve.common import ArtifactRequirements
from pants.jvm.resolve.coursier_fetch import ToolClasspathRequest, materialize_classpath_for_tool
from pants.jvm.strip_jar import strip_jar
from pants.jvm.strip_jar.strip_jar import StripJarRequest
from pants.jvm.strip_jar.strip_jar import strip_jar as strip_jar_get
from pants.jvm.subsystems import JvmSubsystem
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class CompileScalaSourceRequest(ClasspathEntryRequest):
    field_sets = (ScalaFieldSet, ScalaGeneratorFieldSet)
    field_sets_consume_only = (JavaFieldSet, JavaGeneratorFieldSet)


@dataclass(frozen=True)
class ScalaLibraryRequest:
    version: ScalaVersion


# TODO: This code is duplicated in the scalac and BSP rules.
def compute_output_jar_filename(ctgt: CoarsenedTarget) -> str:
    return f"{ctgt.representative.address.path_safe_spec}.scalac.jar"


@rule(desc="Compile with scalac")
async def compile_scala_source(
    scala: ScalaSubsystem,
    jvm: JvmSubsystem,
    scalac: Scalac,
    bash: BashBinary,
    zip_binary: ZipBinary,
    request: CompileScalaSourceRequest,
) -> FallibleClasspathEntry:
    # Request classpath entries for our direct dependencies.
    dependency_cpers = await compile_classpath_entries(
        **implicitly(ClasspathDependenciesRequest(request))
    )
    direct_dependency_classpath_entries = dependency_cpers.if_all_succeeded()

    if direct_dependency_classpath_entries is None:
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.DEPENDENCY_FAILED,
            output=None,
            exit_code=1,
        )

    scala_version = scala.version_for_resolve(request.resolve.name)
    scala_artifacts = await resolve_scala_artifacts_for_version(
        ScalaArtifactsForVersionRequest(scala_version)
    )

    component_members_with_sources = tuple(
        t for t in request.component.members if t.has_field(SourcesField)
    )
    component_members_and_source_files = zip(
        component_members_with_sources,
        await concurrently(
            # Some Scalac plugins (i.e. SemanticDB) require us to use stripped source files so the plugin
            # would emit compilation output that correlates with the appropiate paths in the input files.
            strip_source_roots(
                **implicitly(
                    SourceFilesRequest(
                        (t.get(SourcesField),),
                        for_sources_types=(ScalaSourceField, JavaSourceField),
                        enable_codegen=True,
                    )
                )
            )
            for t in component_members_with_sources
        ),
    )

    plugins_ = await concurrently(
        resolve_scala_plugins_for_target(
            ScalaPluginsForTargetRequest(target, request.resolve.name), **implicitly()
        )
        for target in request.component.members
    )
    plugins_request = ScalaPluginsRequest.from_target_plugins(plugins_, request.resolve)
    local_plugins = await fetch_plugins(plugins_request)

    component_members_and_scala_source_files = [
        (target, sources)
        for target, sources in component_members_and_source_files
        if sources.snapshot.digest != EMPTY_DIGEST
    ]

    if not component_members_and_scala_source_files:
        # Is a generator, and so exports all of its direct deps.
        exported_digest = await merge_digests(
            MergeDigests(cpe.digest for cpe in direct_dependency_classpath_entries)
        )
        classpath_entry = ClasspathEntry.merge(exported_digest, direct_dependency_classpath_entries)
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.SUCCEEDED,
            output=classpath_entry,
            exit_code=0,
        )

    toolcp_relpath = "__toolcp"
    local_scalac_plugins_relpath = "__localplugincp"
    usercp = "__cp"

    user_classpath = Classpath(direct_dependency_classpath_entries, request.resolve)

    tool_classpath, sources_digest, jdk = await concurrently(
        materialize_classpath_for_tool(
            ToolClasspathRequest(
                artifact_requirements=ArtifactRequirements.from_coordinates(
                    [
                        scala_artifacts.compiler_coordinate,
                        scala_artifacts.library_coordinate,
                    ]
                ),
            )
        ),
        merge_digests(
            MergeDigests(
                (sources.snapshot.digest for _, sources in component_members_and_scala_source_files)
            )
        ),
        prepare_jdk_environment(**implicitly(JdkRequest.from_target(request.component))),
    )

    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
        local_scalac_plugins_relpath: local_plugins.classpath.digest,
    }
    extra_nailgun_keys = tuple(extra_immutable_input_digests)
    extra_immutable_input_digests.update(user_classpath.immutable_inputs(prefix=usercp))

    classpath_arg = ":".join(user_classpath.immutable_inputs_args(prefix=usercp))

    output_file = compute_output_jar_filename(request.component)
    compilation_output_dir = "__out"
    compilation_empty_dir = await create_digest(CreateDigest([Directory(compilation_output_dir)]))
    merged_digest = await merge_digests(MergeDigests([sources_digest, compilation_empty_dir]))
    compile_result = await execute_process(
        **implicitly(
            JvmProcess(
                jdk=jdk,
                classpath_entries=tool_classpath.classpath_entries(toolcp_relpath),
                argv=[
                    scala_artifacts.compiler_main,
                    "-bootclasspath",
                    ":".join(tool_classpath.classpath_entries(toolcp_relpath)),
                    *local_plugins.args(local_scalac_plugins_relpath),
                    *(("-classpath", classpath_arg) if classpath_arg else ()),
                    *scalac.parsed_args_for_resolve(request.resolve.name),
                    "-d",
                    compilation_output_dir,
                    *sorted(
                        chain.from_iterable(
                            sources.snapshot.files
                            for _, sources in component_members_and_scala_source_files
                        )
                    ),
                ],
                input_digest=merged_digest,
                extra_immutable_input_digests=extra_immutable_input_digests,
                extra_nailgun_keys=extra_nailgun_keys,
                output_directories=(compilation_output_dir,),
                description=f"Compile {request.component} with scalac",
                level=LogLevel.DEBUG,
            )
        )
    )
    output: ClasspathEntry | None = None
    if compile_result.exit_code == 0:
        # We package the outputs into a JAR file in a similar way as how it's
        # done in the `javac.py` implementation
        jar_result = await execute_process_or_raise(
            **implicitly(
                Process(
                    argv=[
                        bash.path,
                        "-c",
                        " ".join(
                            [
                                "cd",
                                compilation_output_dir,
                                ";",
                                zip_binary.path,
                                "-r",
                                f"../{output_file}",
                                ".",
                            ]
                        ),
                    ],
                    input_digest=compile_result.output_digest,
                    output_files=(output_file,),
                    description=f"Capture outputs of {request.component} for scalac",
                    level=LogLevel.TRACE,
                    cache_scope=ProcessCacheScope.LOCAL_SUCCESSFUL,
                )
            )
        )
        output_digest = jar_result.output_digest

        if jvm.reproducible_jars:
            output_digest = await strip_jar_get(
                **implicitly(StripJarRequest(digest=output_digest, filenames=(output_file,)))
            )

        output = ClasspathEntry(output_digest, (output_file,), direct_dependency_classpath_entries)

    return FallibleClasspathEntry.from_fallible_process_result(
        str(request.component),
        compile_result,
        output,
    )


@rule
async def fetch_scala_library(request: ScalaLibraryRequest) -> ClasspathEntry:
    scala_artifacts = await resolve_scala_artifacts_for_version(
        ScalaArtifactsForVersionRequest(request.version)
    )
    tcp = await materialize_classpath_for_tool(
        ToolClasspathRequest(
            artifact_requirements=ArtifactRequirements.from_coordinates(
                [
                    scala_artifacts.library_coordinate,
                ]
            ),
        )
    )

    return ClasspathEntry(tcp.digest, tcp.content.files)


def rules():
    return [
        *collect_rules(),
        *jvm_compile_rules(),
        *scala_artifact_rules(),
        *scalac_plugins_rules(),
        *versions.rules(),
        *strip_jar.rules(),
        UnionRule(ClasspathEntryRequest, CompileScalaSourceRequest),
    ]
