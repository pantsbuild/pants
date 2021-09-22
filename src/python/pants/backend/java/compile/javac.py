# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from itertools import chain

from pants.backend.java.compile.javac_binary import JavacBinary
from pants.backend.java.target_types import JavaSourceField
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, MergeDigests, RemovePrefix
from pants.engine.process import BashBinary, FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTarget, CoarsenedTargets, FieldSet, Sources, Targets
from pants.engine.unions import UnionRule
from pants.jvm.resolve.coursier_fetch import (
    CoursierLockfileForTargetRequest,
    CoursierResolvedLockfile,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)
from pants.jvm.resolve.coursier_setup import Coursier
from pants.util.logging import LogLevel
from pants.util.strutil import strip_v2_chroot_path

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


@dataclass(frozen=True)
class CompiledClassfiles:
    digest: Digest


class CompileResult(Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEPENDENCY_FAILED = "dependency failed"


@dataclass(frozen=True)
class FallibleCompiledClassfiles(EngineAwareReturnType):
    description: str
    result: CompileResult
    output: CompiledClassfiles | None
    exit_code: int
    stdout: str | None = None
    stderr: str | None = None

    @classmethod
    def from_fallible_process_result(
        cls,
        description: str,
        process_result: FallibleProcessResult,
        output: CompiledClassfiles | None,
        *,
        strip_chroot_path: bool = False,
    ) -> FallibleCompiledClassfiles:
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        exit_code = process_result.exit_code
        # TODO: Coursier renders this line on macOS.
        stderr = "\n".join(
            line
            for line in prep_output(process_result.stderr).splitlines()
            if line != "setrlimit to increase file descriptor limit failed, errno 22"
        )
        return cls(
            description=description,
            result=(CompileResult.SUCCEEDED if exit_code == 0 else CompileResult.FAILED),
            output=output,
            exit_code=exit_code,
            stdout=prep_output(process_result.stdout),
            stderr=stderr,
        )

    def level(self) -> LogLevel:
        return LogLevel.ERROR if self.exit_code != 0 else LogLevel.INFO

    def message(self) -> str:
        message = self.description
        message += (
            " succeeded." if self.exit_code == 0 else f" failed (exit code {self.exit_code})."
        )
        if self.stdout:
            message += f"\n{self.stdout}"
        if self.stderr:
            message += f"\n{self.stderr}"
        return message

    def cacheable(self) -> bool:
        # Failed compile outputs should be re-rendered in every run.
        return self.exit_code == 0


@rule(desc="Compile with javac")
async def compile_java_source(
    bash: BashBinary,
    coursier: Coursier,
    javac_binary: JavacBinary,
    request: CompileJavaSourceRequest,
) -> FallibleCompiledClassfiles:
    component_members_with_sources = tuple(
        t for t in request.component.members if t.has_field(Sources)
    )
    component_members_and_source_files = zip(
        component_members_with_sources,
        await MultiGet(
            Get(
                SourceFiles,
                SourceFilesRequest(
                    (t.get(Sources),),
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
        return FallibleCompiledClassfiles(
            description=str(request.component),
            result=CompileResult.SUCCEEDED,
            output=CompiledClassfiles(digest=EMPTY_DIGEST),
            exit_code=0,
        )

    # Target coarsening currently doesn't perform dep expansion, which matters for targets
    # with multiple sources that expand to individual source subtargets.
    # We expand the dependencies explicitly here before coarsening, but ideally this could
    # be done somehow during coarsening.
    # TODO: Should component dependencies be filtered out here if they were only brought in by component members which were
    #   filtered out above (due to having no JavaSources to contribute)?  If so, that will likely required extending
    #   the CoarsenedTargets API to include more complete dependency information, or to support such filtering directly.
    expanded_direct_deps = await Get(Targets, Addresses(request.component.dependencies))
    coarsened_direct_deps = await Get(
        CoarsenedTargets, Addresses(t.address for t in expanded_direct_deps)
    )

    lockfile = await Get(
        CoursierResolvedLockfile,
        CoursierLockfileForTargetRequest(Targets(request.component.members)),
    )
    direct_dependency_classfiles_fallible = await MultiGet(
        Get(FallibleCompiledClassfiles, CompileJavaSourceRequest(component=coarsened_dep))
        for coarsened_dep in coarsened_direct_deps
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

    materialized_classpath, merged_direct_dependency_classfiles_digest = await MultiGet(
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                prefix="__thirdpartycp",
                lockfiles=(lockfile,),
            ),
        ),
        Get(Digest, MergeDigests(classfiles.digest for classfiles in direct_dependency_classfiles)),
    )

    usercp_relpath = "__usercp"
    prefixed_direct_dependency_classfiles_digest = await Get(
        Digest, AddPrefix(merged_direct_dependency_classfiles_digest, usercp_relpath)
    )

    classpath_arg = usercp_relpath
    third_party_classpath_arg = materialized_classpath.classpath_arg()
    if third_party_classpath_arg:
        classpath_arg = ":".join([classpath_arg, third_party_classpath_arg])

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                prefixed_direct_dependency_classfiles_digest,
                materialized_classpath.digest,
                javac_binary.digest,
                *(
                    sources.snapshot.digest
                    for _, sources in component_members_and_java_source_files
                ),
            )
        ),
    )

    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                bash.path,
                javac_binary.javac_wrapper_script,
                "-cp",
                classpath_arg,
                "-d",
                "classfiles",
                *sorted(
                    chain.from_iterable(
                        sources.snapshot.files
                        for _, sources in component_members_and_java_source_files
                    )
                ),
            ],
            input_digest=merged_digest,
            output_directories=("classfiles",),
            description=f"Compile {request.component.members} with javac",
            level=LogLevel.DEBUG,
        ),
    )
    output: CompiledClassfiles | None = None
    if process_result.exit_code == 0:
        stripped_classfiles_digest = await Get(
            Digest, RemovePrefix(process_result.output_digest, "classfiles")
        )
        output = CompiledClassfiles(stripped_classfiles_digest)

    return FallibleCompiledClassfiles.from_fallible_process_result(
        str(request.component),
        process_result,
        output,
    )


@rule
def required_classfiles(fallible_result: FallibleCompiledClassfiles) -> CompiledClassfiles:
    if fallible_result.result == CompileResult.SUCCEEDED:
        assert fallible_result.output
        return fallible_result.output
    # NB: The compile outputs will already have been streamed as FallibleCompiledClassfiles finish.
    raise Exception("Compile failed.")


@rule(desc="Check compilation for javac", level=LogLevel.DEBUG)
async def javac_check(request: JavacCheckRequest) -> CheckResults:
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(field_set.address for field_set in request.field_sets)
    )

    # TODO: This should be fallible so that we exit cleanly.
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
        UnionRule(CheckRequest, JavacCheckRequest),
    ]
