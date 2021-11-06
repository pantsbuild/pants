# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain

from pants.backend.scala.compile.scala_subsystem import ScalaSubsystem
from pants.backend.scala.target_types import ScalaSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, MergeDigests, Snapshot
from pants.engine.process import BashBinary, FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTarget, CoarsenedTargets, FieldSet, SourcesField
from pants.jvm.compile import CompiledClassfiles, CompileResult, FallibleCompiledClassfiles
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirements,
    Coordinate,
    Coordinates,
    CoursierResolvedLockfile,
    CoursierResolveKey,
    FilterDependenciesRequest,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)
from pants.jvm.resolve.coursier_setup import Coursier
from pants.jvm.target_types import JvmArtifactFieldSet
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScalacFieldSet(FieldSet):
    required_fields = (ScalaSourceField,)

    sources: ScalaSourceField


@dataclass(frozen=True)
class CompileScalaSourceRequest:
    component: CoarsenedTarget
    resolve: CoursierResolveKey


@rule(desc="Compile with scalac")
async def compile_scala_source(
    bash: BashBinary,
    coursier: Coursier,
    jdk_setup: JdkSetup,
    scala: ScalaSubsystem,
    request: CompileScalaSourceRequest,
) -> FallibleCompiledClassfiles:
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
                    for_sources_types=(ScalaSourceField,),
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
        return FallibleCompiledClassfiles(
            description=str(request.component),
            result=CompileResult.SUCCEEDED,
            output=CompiledClassfiles(digest=EMPTY_DIGEST),
            exit_code=0,
        )

    filter_coords = Coordinates(
        (
            Coordinate.from_jvm_artifact_target(dep)
            for item in CoarsenedTargets(request.component.dependencies).closure()
            for dep in item.members
            if JvmArtifactFieldSet.is_applicable(dep)
        )
    )

    unfiltered_lockfile = await Get(CoursierResolvedLockfile, CoursierResolveKey, request.resolve)
    lockfile = await Get(
        CoursierResolvedLockfile, FilterDependenciesRequest(filter_coords, unfiltered_lockfile)
    )

    transitive_dependency_classfiles_fallible = await MultiGet(
        Get(
            FallibleCompiledClassfiles,
            CompileScalaSourceRequest(component=component, resolve=request.resolve),
        )
        for component in CoarsenedTargets(request.component.dependencies).closure()
    )
    transitive_dependency_classfiles = [
        fcc.output for fcc in transitive_dependency_classfiles_fallible if fcc.output
    ]
    if len(transitive_dependency_classfiles) != len(transitive_dependency_classfiles_fallible):
        return FallibleCompiledClassfiles(
            description=str(request.component),
            result=CompileResult.DEPENDENCY_FAILED,
            output=None,
            exit_code=1,
        )

    (
        tool_classpath,
        materialized_classpath,
        merged_transitive_dependency_classfiles_digest,
    ) = await MultiGet(
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                prefix="__toolcp",
                artifact_requirements=(
                    ArtifactRequirements(
                        [
                            Coordinate(
                                group="org.scala-lang",
                                artifact="scala-compiler",
                                version=scala.version,
                            ),
                            Coordinate(
                                group="org.scala-lang",
                                artifact="scala-library",
                                version=scala.version,
                            ),
                        ]
                    ),
                ),
            ),
        ),
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                prefix="__thirdpartycp",
                lockfiles=(lockfile,),
            ),
        ),
        Get(
            Digest,
            MergeDigests(classfiles.digest for classfiles in transitive_dependency_classfiles),
        ),
    )

    usercp_relpath = "__usercp"
    prefixed_transitive_dependency_classpath = await Get(
        Snapshot, AddPrefix(merged_transitive_dependency_classfiles_digest, usercp_relpath)
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                prefixed_transitive_dependency_classpath.digest,
                tool_classpath.digest,
                materialized_classpath.digest,
                jdk_setup.digest,
                *(
                    sources.snapshot.digest
                    for _, sources in component_members_and_scala_source_files
                ),
            )
        ),
    )

    classpath_arg = ":".join(
        [
            *prefixed_transitive_dependency_classpath.files,
            *materialized_classpath.classpath_entries(),
        ]
    )

    output_file = f"{request.component.representative.address.path_safe_spec}.jar"
    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                *jdk_setup.args(bash, tool_classpath.classpath_entries()),
                "scala.tools.nsc.Main",
                "-bootclasspath",
                ":".join(tool_classpath.classpath_entries()),
                *(("-classpath", classpath_arg) if classpath_arg else ()),
                "-d",
                output_file,
                *sorted(
                    chain.from_iterable(
                        sources.snapshot.files
                        for _, sources in component_members_and_scala_source_files
                    )
                ),
            ],
            input_digest=merged_digest,
            use_nailgun=jdk_setup.digest,
            output_files=(output_file,),
            description=f"Compile {request.component} with scalac",
            level=LogLevel.DEBUG,
            append_only_caches=jdk_setup.append_only_caches,
            env=jdk_setup.env,
        ),
    )
    output: CompiledClassfiles | None = None
    if process_result.exit_code == 0:
        output = CompiledClassfiles(process_result.output_digest)

    return FallibleCompiledClassfiles.from_fallible_process_result(
        str(request.component),
        process_result,
        output,
    )


def rules():
    return [
        *collect_rules(),
        *jvm_compile_rules(),
    ]
