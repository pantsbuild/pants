# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    Digest,
    DigestSubset,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
)
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest, Sources, Target, Targets
from pants.java.target_types import JavaSources
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
class CompileJavaSourceRequest:
    target: Target


@dataclass(frozen=True)
class CompiledClassfiles:
    digest: Digest


@rule(level=LogLevel.DEBUG)
async def compile_java_source(
    coursier: Coursier,
    request: CompileJavaSourceRequest,
) -> CompiledClassfiles:
    sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            (request.target.get(Sources),),
            for_sources_types=(JavaSources,),
            enable_codegen=True,
        ),
    )
    if sources.snapshot.digest == EMPTY_DIGEST:
        return CompiledClassfiles(digest=EMPTY_DIGEST)

    direct_deps = await Get(Targets, DependenciesRequest(request.target.get(Dependencies)))
    direct_dependency_classfiles = await MultiGet(
        Get(CompiledClassfiles, CompileJavaSourceRequest(target=target)) for target in direct_deps
    )
    lockfile = await Get(
        CoursierResolvedLockfile, CoursierLockfileForTargetRequest(Targets((request.target,)))
    )

    materialized_classpath = await Get(
        MaterializedClasspath,
        MaterializedClasspathRequest(
            prefix="thirdpartycp",
            lockfiles=(lockfile,),
        ),
    )
    merged_direct_dependency_classfiles_digest = await Get(
        Digest, MergeDigests(classfiles.digest for classfiles in direct_dependency_classfiles)
    )
    prefixed_direct_dependency_classfiles_digest = await Get(
        Digest, AddPrefix(merged_direct_dependency_classfiles_digest, "usercp")
    )

    classpath_arg = "usercp"
    third_party_classpath_arg = materialized_classpath.classpath_arg()
    if third_party_classpath_arg:
        classpath_arg = ":".join([classpath_arg, third_party_classpath_arg])

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                sources.snapshot.digest,
                prefixed_direct_dependency_classfiles_digest,
                materialized_classpath.digest,
                coursier.digest,
            )
        ),
    )

    process_result = await Get(
        ProcessResult,
        Process(
            argv=[
                "/bin/sh",
                coursier.javac,
                coursier.coursier.exe,
                "--class-path",
                classpath_arg,
                "-d",
                "classfiles",
                *sources.files,
            ],
            input_digest=merged_digest,
            output_directories=("classfiles",),
            description="Run javac",
            level=LogLevel.DEBUG,
        ),
    )
    classfiles_digest = await Get(
        Digest, DigestSubset(process_result.output_digest, PathGlobs(["classfiles/**"]))
    )
    stripped_classfiles_digest = await Get(Digest, RemovePrefix(classfiles_digest, "classfiles"))
    return CompiledClassfiles(digest=stripped_classfiles_digest)


def rules():
    return [
        *collect_rules(),
    ]
