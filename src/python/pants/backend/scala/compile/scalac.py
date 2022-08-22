# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain

from pants.backend.java.target_types import JavaFieldSet, JavaGeneratorFieldSet, JavaSourceField
from pants.backend.scala.compile.scalac_plugins import (
    ScalaPlugins,
    ScalaPluginsForTargetRequest,
    ScalaPluginsRequest,
    ScalaPluginTargetsForTarget,
)
from pants.backend.scala.compile.scalac_plugins import rules as scalac_plugins_rules
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import ScalaFieldSet, ScalaGeneratorFieldSet, ScalaSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTarget, SourcesField
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.compile import (
    ClasspathDependenciesRequest,
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntries,
    FallibleClasspathEntry,
)
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.resolve.common import ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.strip_jar.strip_jar import StripJarRequest
from pants.jvm.subsystems import JvmSubsystem
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class CompileScalaSourceRequest(ClasspathEntryRequest):
    field_sets = (ScalaFieldSet, ScalaGeneratorFieldSet)
    field_sets_consume_only = (JavaFieldSet, JavaGeneratorFieldSet)


@dataclass(frozen=True)
class ScalaLibraryRequest:
    version: str


# TODO: This code is duplicated in the scalac and BSP rules.
def compute_output_jar_filename(ctgt: CoarsenedTarget) -> str:
    return f"{ctgt.representative.address.path_safe_spec}.scalac.jar"


@rule(desc="Compile with scalac")
async def compile_scala_source(
    scala: ScalaSubsystem,
    jvm: JvmSubsystem,
    scalac: Scalac,
    request: CompileScalaSourceRequest,
) -> FallibleClasspathEntry:

    # Request classpath entries for our direct dependencies.
    dependency_cpers = await Get(FallibleClasspathEntries, ClasspathDependenciesRequest(request))
    direct_dependency_classpath_entries = dependency_cpers.if_all_succeeded()

    if direct_dependency_classpath_entries is None:
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.DEPENDENCY_FAILED,
            output=None,
            exit_code=1,
        )

    scala_version = scala.version_for_resolve(request.resolve.name)

    component_members_with_sources = tuple(
        t for t in request.component.members if t.has_field(SourcesField)
    )
    component_members_and_source_files = zip(
        component_members_with_sources,
        await MultiGet(
            Get(
                SourceFiles,
                SourceFilesRequest(
                    (t.get(SourcesField),),
                    for_sources_types=(ScalaSourceField, JavaSourceField),
                    enable_codegen=True,
                ),
            )
            for t in component_members_with_sources
        ),
    )

    plugins_ = await MultiGet(
        Get(
            ScalaPluginTargetsForTarget,
            ScalaPluginsForTargetRequest(target, request.resolve.name),
        )
        for target in request.component.members
    )
    plugins_request = ScalaPluginsRequest.from_target_plugins(plugins_, request.resolve)
    local_plugins = await Get(ScalaPlugins, ScalaPluginsRequest, plugins_request)

    component_members_and_scala_source_files = [
        (target, sources)
        for target, sources in component_members_and_source_files
        if sources.snapshot.digest != EMPTY_DIGEST
    ]

    if not component_members_and_scala_source_files:
        # Is a generator, and so exports all of its direct deps.
        exported_digest = await Get(
            Digest, MergeDigests(cpe.digest for cpe in direct_dependency_classpath_entries)
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

    tool_classpath, sources_digest, jdk = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(
                artifact_requirements=ArtifactRequirements.from_coordinates(
                    [
                        Coordinate(
                            group="org.scala-lang",
                            artifact="scala-compiler",
                            version=scala_version,
                        ),
                        Coordinate(
                            group="org.scala-lang",
                            artifact="scala-library",
                            version=scala_version,
                        ),
                    ]
                ),
            ),
        ),
        Get(
            Digest,
            MergeDigests(
                (sources.snapshot.digest for _, sources in component_members_and_scala_source_files)
            ),
        ),
        Get(JdkEnvironment, JdkRequest, JdkRequest.from_target(request.component)),
    )

    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
        local_scalac_plugins_relpath: local_plugins.classpath.digest,
    }
    extra_nailgun_keys = tuple(extra_immutable_input_digests)
    extra_immutable_input_digests.update(user_classpath.immutable_inputs(prefix=usercp))

    classpath_arg = ":".join(user_classpath.immutable_inputs_args(prefix=usercp))

    output_file = compute_output_jar_filename(request.component)
    process_result = await Get(
        FallibleProcessResult,
        JvmProcess(
            jdk=jdk,
            classpath_entries=tool_classpath.classpath_entries(toolcp_relpath),
            argv=[
                "scala.tools.nsc.Main",
                "-bootclasspath",
                ":".join(tool_classpath.classpath_entries(toolcp_relpath)),
                *local_plugins.args(local_scalac_plugins_relpath),
                *(("-classpath", classpath_arg) if classpath_arg else ()),
                *scalac.args,
                # NB: We set a non-existent main-class so that using `-d` produces a `jar` manifest
                # with stable content.
                "-Xmain-class",
                "no.main.class",
                "-d",
                output_file,
                *sorted(
                    chain.from_iterable(
                        sources.snapshot.files
                        for _, sources in component_members_and_scala_source_files
                    )
                ),
            ],
            input_digest=sources_digest,
            extra_immutable_input_digests=extra_immutable_input_digests,
            extra_nailgun_keys=extra_nailgun_keys,
            output_files=(output_file,),
            description=f"Compile {request.component} with scalac",
            level=LogLevel.DEBUG,
        ),
    )
    output: ClasspathEntry | None = None
    if process_result.exit_code == 0:
        output_digest = process_result.output_digest
        if jvm.reproducible_jars:
            output_digest = await Get(
                Digest, StripJarRequest(digest=output_digest, filenames=(output_file,))
            )

        output = ClasspathEntry(output_digest, (output_file,), direct_dependency_classpath_entries)

    return FallibleClasspathEntry.from_fallible_process_result(
        str(request.component),
        process_result,
        output,
    )


@rule
async def fetch_scala_library(request: ScalaLibraryRequest) -> ClasspathEntry:
    tcp = await Get(
        ToolClasspath,
        ToolClasspathRequest(
            artifact_requirements=ArtifactRequirements.from_coordinates(
                [
                    Coordinate(
                        group="org.scala-lang",
                        artifact="scala-library",
                        version=request.version,
                    ),
                ]
            ),
        ),
    )

    return ClasspathEntry(tcp.digest, tcp.content.files)


def rules():
    return [
        *collect_rules(),
        *jvm_compile_rules(),
        *scalac_plugins_rules(),
        UnionRule(ClasspathEntryRequest, CompileScalaSourceRequest),
    ]
