# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain

from pants.backend.java.compile.javac_binary import JavacBinary
from pants.backend.java.target_types import JavaSources
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, MergeDigests, RemovePrefix
from pants.engine.process import BashBinary, Process, ProcessResult
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

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JavacFieldSet(FieldSet):
    required_fields = (JavaSources,)

    sources: JavaSources


class JavacCheckRequest(CheckRequest):
    field_set_type = JavacFieldSet


@dataclass(frozen=True)
class CompileJavaSourceRequest:
    component: CoarsenedTarget


@dataclass(frozen=True)
class CompiledClassfiles:
    digest: Digest


@rule(level=LogLevel.DEBUG)
async def compile_java_source(
    bash: BashBinary,
    coursier: Coursier,
    javac_binary: JavacBinary,
    request: CompileJavaSourceRequest,
) -> CompiledClassfiles:
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
                    for_sources_types=(JavaSources,),
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
        return CompiledClassfiles(digest=EMPTY_DIGEST)

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
    direct_dependency_classfiles = await MultiGet(
        Get(CompiledClassfiles, CompileJavaSourceRequest(component=coarsened_dep))
        for coarsened_dep in coarsened_direct_deps
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
        ProcessResult,
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
    stripped_classfiles_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, "classfiles")
    )
    return CompiledClassfiles(digest=stripped_classfiles_digest)


@rule(desc="Check compilation for javac", level=LogLevel.DEBUG)
async def javac_check(request: JavacCheckRequest) -> CheckResults:
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(field_set.address for field_set in request.field_sets)
    )

    # TODO: This should be fallible so that we exit cleanly.
    _ = await MultiGet(
        Get(CompiledClassfiles, CompileJavaSourceRequest(component=t)) for t in coarsened_targets
    )

    # TODO: non-mock stdout/stderr.
    return CheckResults(
        [
            CheckResult(0, stdout="", stderr="", partition_description=field_set.address.spec)
            for field_set in request.field_sets
        ],
        checker_name="javac",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(CheckRequest, JavacCheckRequest),
    ]
