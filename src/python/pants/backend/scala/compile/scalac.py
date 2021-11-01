# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain

from pants.backend.scala.compile.scala_subsystem import ScalaSubsystem
from pants.backend.scala.target_types import ScalaSourceField
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    MergeDigests,
    RemovePrefix,
)
from pants.engine.process import BashBinary, FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTarget, CoarsenedTargets, FieldSet, SourcesField, Targets
from pants.engine.unions import UnionRule
from pants.jvm.compile import CompiledClassfiles, CompileResult, FallibleCompiledClassfiles
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirements,
    Coordinate,
    CoursierResolvedLockfile,
    CoursierResolveKey,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)
from pants.jvm.resolve.coursier_setup import Coursier
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScalacFieldSet(FieldSet):
    required_fields = (ScalaSourceField,)

    sources: ScalaSourceField


class ScalacCheckRequest(CheckRequest):
    field_set_type = ScalacFieldSet


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

    lockfile = await Get(CoursierResolvedLockfile, CoursierResolveKey, request.resolve)

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

    dest_dir = "classfiles"
    (
        tool_classpath,
        third_party_classpath,
        merged_transitive_dependency_classfiles_digest,
        dest_dir_digest,
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
        Get(
            Digest,
            CreateDigest([Directory(dest_dir)]),
        ),
    )

    usercp_relpath = "__usercp"
    prefixed_transitive_dependency_classfiles_digest = await Get(
        Digest, AddPrefix(merged_transitive_dependency_classfiles_digest, usercp_relpath)
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                prefixed_transitive_dependency_classfiles_digest,
                tool_classpath.digest,
                third_party_classpath.digest,
                dest_dir_digest,
                jdk_setup.digest,
                *(
                    sources.snapshot.digest
                    for _, sources in component_members_and_scala_source_files
                ),
            )
        ),
    )

    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                *jdk_setup.args(bash, tool_classpath.classpath_entries()),
                "scala.tools.nsc.Main",
                "-bootclasspath",
                ":".join(tool_classpath.classpath_entries()),
                "-classpath",
                ":".join([*third_party_classpath.classpath_entries(), usercp_relpath]),
                "-d",
                dest_dir,
                *sorted(
                    chain.from_iterable(
                        sources.snapshot.files
                        for _, sources in component_members_and_scala_source_files
                    )
                ),
            ],
            input_digest=merged_digest,
            use_nailgun=jdk_setup.digest,
            output_directories=(dest_dir,),
            description=f"Compile {request.component.members} with scalac",
            level=LogLevel.DEBUG,
            append_only_caches=jdk_setup.append_only_caches,
            env=jdk_setup.env,
        ),
    )
    output: CompiledClassfiles | None = None
    if process_result.exit_code == 0:
        stripped_classfiles_digest = await Get(
            Digest, RemovePrefix(process_result.output_digest, dest_dir)
        )
        output = CompiledClassfiles(stripped_classfiles_digest)

    return FallibleCompiledClassfiles.from_fallible_process_result(
        str(request.component),
        process_result,
        output,
    )


@rule(desc="Check compilation for Scala", level=LogLevel.DEBUG)
async def scalac_check(request: ScalacCheckRequest) -> CheckResults:
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(field_set.address for field_set in request.field_sets)
    )

    resolves = await MultiGet(
        Get(CoursierResolveKey, Targets(t.members)) for t in coarsened_targets
    )

    # TODO: This should be fallible so that we exit cleanly.
    results = await MultiGet(
        Get(FallibleCompiledClassfiles, CompileScalaSourceRequest(component=t, resolve=r))
        for t, r in zip(coarsened_targets, resolves)
    )

    # NB: We return CheckResults with exit codes for the root targets, but we do not pass
    # stdout/stderr because it will already have been rendered as streaming.
    return CheckResults(
        [
            CheckResult(
                result.exit_code,
                stdout="",
                stderr="",
                partition_description=str(coarsened_target),
            )
            for result, coarsened_target in zip(results, coarsened_targets)
        ],
        checker_name="scalac",
    )


def rules():
    return [
        *collect_rules(),
        *jvm_compile_rules(),
        UnionRule(CheckRequest, ScalacCheckRequest),
    ]
