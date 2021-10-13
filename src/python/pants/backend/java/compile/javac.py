# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain

from pants.backend.java.target_types import JavaSourceField
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.util_rules.archive import ZipBinary
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    MergeDigests,
    Snapshot,
)
from pants.engine.process import BashBinary, FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTarget, CoarsenedTargets, FieldSet, SourcesField, Targets
from pants.engine.unions import UnionRule
from pants.jvm.compile import CompiledClassfiles, CompileResult, FallibleCompiledClassfiles
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.coursier_fetch import (
    CoursierLockfileForTargetRequest,
    CoursierResolvedLockfile,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JavacFieldSet(FieldSet):
    required_fields = (JavaSourceField,)

    sources: JavaSourceField


class JavacCheckRequest(CheckRequest):
    field_set_type = JavacFieldSet


@dataclass(frozen=True)
class CompileJavaSourceRequest:
    component: CoarsenedTarget


@rule(desc="Compile with javac")
async def compile_java_source(
    bash: BashBinary,
    jdk_setup: JdkSetup,
    zip_binary: ZipBinary,
    request: CompileJavaSourceRequest,
) -> FallibleCompiledClassfiles:
    # Request the component's direct dependency classpath.
    direct_dependency_classfiles_fallible = await MultiGet(
        Get(FallibleCompiledClassfiles, CompileJavaSourceRequest(component=coarsened_dep))
        for coarsened_dep in request.component.dependencies
    )
    direct_dependency_classfiles = [
        fcc.output for fcc in direct_dependency_classfiles_fallible if fcc.output
    ]
    if len(direct_dependency_classfiles) != len(direct_dependency_classfiles_fallible):
        return FallibleCompiledClassfiles(
            description=str(request.component),
            result=CompileResult.DEPENDENCY_FAILED,
            output=None,
            exit_code=1,
        )

    # Then collect the component's sources.
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
                    for_sources_types=(JavaSourceField,),
                    enable_codegen=True,
                ),
            )
            for t in component_members_with_sources
        ),
    )
    component_members_and_java_source_files = [
        (target, sources)
        for target, sources in component_members_and_source_files
        if sources.snapshot.digest != EMPTY_DIGEST
    ]
    if not component_members_and_java_source_files:
        # If the component has no sources, it is acting as an alias for its dependencies: return
        # their merged classpaths.
        dependencies_digest = await Get(
            Digest, MergeDigests(classfiles.digest for classfiles in direct_dependency_classfiles)
        )
        return FallibleCompiledClassfiles(
            description=str(request.component),
            result=CompileResult.SUCCEEDED,
            output=CompiledClassfiles(digest=dependencies_digest),
            exit_code=0,
        )

    lockfile = await Get(
        CoursierResolvedLockfile,
        CoursierLockfileForTargetRequest(Targets(request.component.members)),
    )

    dest_dir = "classfiles"
    (
        materialized_classpath,
        merged_direct_dependency_classpath_digest,
        dest_dir_digest,
    ) = await MultiGet(
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                prefix="__thirdpartycp",
                lockfiles=(lockfile,),
            ),
        ),
        Get(Digest, MergeDigests(classfiles.digest for classfiles in direct_dependency_classfiles)),
        Get(
            Digest,
            CreateDigest([Directory(dest_dir)]),
        ),
    )

    prefixed_direct_dependency_classpath = await Get(
        Snapshot, AddPrefix(merged_direct_dependency_classpath_digest, "__usercp")
    )

    classpath_arg = ":".join(
        [*prefixed_direct_dependency_classpath.files, *materialized_classpath.classpath_entries()]
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                prefixed_direct_dependency_classpath.digest,
                materialized_classpath.digest,
                dest_dir_digest,
                jdk_setup.digest,
                *(
                    sources.snapshot.digest
                    for _, sources in component_members_and_java_source_files
                ),
            )
        ),
    )

    # Compile.
    compile_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                *jdk_setup.args(bash, [f"{jdk_setup.java_home}/lib/tools.jar"]),
                "com.sun.tools.javac.Main",
                *(("-cp", classpath_arg) if classpath_arg else ()),
                "-d",
                dest_dir,
                *sorted(
                    chain.from_iterable(
                        sources.snapshot.files
                        for _, sources in component_members_and_java_source_files
                    )
                ),
            ],
            input_digest=merged_digest,
            use_nailgun=jdk_setup.digest,
            append_only_caches=jdk_setup.append_only_caches,
            output_directories=(dest_dir,),
            description=f"Compile {request.component} with javac",
            level=LogLevel.DEBUG,
        ),
    )
    if compile_result.exit_code != 0:
        return FallibleCompiledClassfiles.from_fallible_process_result(
            str(request.component),
            compile_result,
            None,
        )

    # Jar.
    # NB: We jar up the outputs in a separate process because the nailgun runner cannot support
    # invoking via a `bash` wrapper (since the trailing portion of the command is executed by
    # the nailgun server). We might be able to resolve this in the future via a Javac wrapper shim.
    output_snapshot = await Get(Snapshot, Digest, compile_result.output_digest)
    output_file = f"{request.component.representative.address.path_safe_spec}.jar"
    if output_snapshot.files:
        jar_result = await Get(
            ProcessResult,
            Process(
                argv=[
                    bash.path,
                    "-c",
                    " ".join(
                        ["cd", dest_dir, ";", zip_binary.path, "-r", f"../{output_file}", "."]
                    ),
                ],
                input_digest=compile_result.output_digest,
                output_files=(output_file,),
                description=f"Capture outputs of {request.component} for javac",
                level=LogLevel.TRACE,
            ),
        )
        jar_output_digest = jar_result.output_digest
    else:
        # If there was no output, then do not create a jar file. This may occur, for example, when compiling
        # a `package-info.java` in a single partition.
        jar_output_digest = EMPTY_DIGEST

    return FallibleCompiledClassfiles.from_fallible_process_result(
        str(request.component),
        compile_result,
        CompiledClassfiles(jar_output_digest),
    )


@rule(desc="Check compilation for javac", level=LogLevel.DEBUG)
async def javac_check(request: JavacCheckRequest) -> CheckResults:
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(field_set.address for field_set in request.field_sets)
    )

    results = await MultiGet(
        Get(FallibleCompiledClassfiles, CompileJavaSourceRequest(component=t))
        for t in coarsened_targets
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
        checker_name="javac",
    )


def rules():
    return [
        *collect_rules(),
        *jvm_compile_rules(),
        UnionRule(CheckRequest, JavacCheckRequest),
    ]
