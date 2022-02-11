# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain

from pants.backend.java.target_types import JavaFieldSet, JavaGeneratorFieldSet, JavaSourceField
from pants.backend.scala.compile.scalac_plugins import GlobalScalacPlugins
from pants.backend.scala.compile.scalac_plugins import rules as scalac_plugins_rules
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import ScalaFieldSet, ScalaGeneratorFieldSet, ScalaSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import SourcesField
from pants.engine.unions import UnionMembership, UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.compile import (
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntry,
)
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.resolve.common import ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class CompileScalaSourceRequest(ClasspathEntryRequest):
    field_sets = (ScalaFieldSet, ScalaGeneratorFieldSet)
    field_sets_consume_only = (JavaFieldSet, JavaGeneratorFieldSet)


@dataclass(frozen=True)
class ScalaLibraryRequest:
    version: str


@rule(desc="Compile with scalac")
async def compile_scala_source(
    scala: ScalaSubsystem,
    scalac: Scalac,
    scalac_plugins: GlobalScalacPlugins,
    union_membership: UnionMembership,
    request: CompileScalaSourceRequest,
) -> FallibleClasspathEntry:
    # Request classpath entries for our direct dependencies.
    direct_dependency_classpath_entries = FallibleClasspathEntry.if_all_succeeded(
        await MultiGet(
            Get(
                FallibleClasspathEntry,
                ClasspathEntryRequest,
                ClasspathEntryRequest.for_targets(
                    union_membership, component=coarsened_dep, resolve=request.resolve
                ),
            )
            for coarsened_dep in request.component.dependencies
        )
    )
    if direct_dependency_classpath_entries is None:
        return FallibleClasspathEntry(
            description=str(request.component),
            result=CompileResult.DEPENDENCY_FAILED,
            output=None,
            exit_code=1,
        )

    all_dependency_jars = [
        filename
        for dependency in direct_dependency_classpath_entries
        for filename in dependency.filenames
    ]

    jdk = await Get(JdkEnvironment, JdkRequest, JdkRequest.from_target(request.component))
    scala_version = scala.version_for_resolve(request.resolve.name)

    # TODO(14171): Stop-gap for making sure that scala supplies all of its dependencies to
    # deploy targets.
    if not any(
        filename.startswith("org.scala-lang_scala-library_") for filename in all_dependency_jars
    ):
        scala_library = await Get(ClasspathEntry, ScalaLibraryRequest(scala_version))
        direct_dependency_classpath_entries += (scala_library,)

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
    scalac_plugins_relpath = "__plugincp"
    usercp = "__cp"

    user_classpath = Classpath(direct_dependency_classpath_entries, request.resolve)

    tool_classpath, sources_digest = await MultiGet(
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
    )

    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
        scalac_plugins_relpath: scalac_plugins.classpath.digest,
    }
    extra_nailgun_keys = tuple(extra_immutable_input_digests)
    extra_immutable_input_digests.update(user_classpath.immutable_inputs(prefix=usercp))

    classpath_arg = ":".join(user_classpath.immutable_inputs_args(prefix=usercp))

    output_file = f"{request.component.representative.address.path_safe_spec}.scalac.jar"
    process_result = await Get(
        FallibleProcessResult,
        JvmProcess(
            jdk=jdk,
            classpath_entries=tool_classpath.classpath_entries(toolcp_relpath),
            argv=[
                "scala.tools.nsc.Main",
                "-bootclasspath",
                ":".join(tool_classpath.classpath_entries(toolcp_relpath)),
                *scalac_plugins.args(scalac_plugins_relpath),
                *(("-classpath", classpath_arg) if classpath_arg else ()),
                *scalac.args,
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
        output = ClasspathEntry(
            process_result.output_digest, (output_file,), direct_dependency_classpath_entries
        )

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
