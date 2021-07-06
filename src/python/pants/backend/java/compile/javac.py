# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.java.compile.javac_binary import JavacBinary
from pants.backend.java.target_types import JavaSources
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, MergeDigests, RemovePrefix
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest, Sources, Target, Targets
from pants.jvm.resolve.coursier_fetch import (
    CoursierLockfileForTargetRequest,
    CoursierResolvedLockfile,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)
from pants.jvm.resolve.coursier_setup import Coursier
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class JavacSubsystem(Subsystem):
    options_scope = "javac"
    help = "The javac Java source compiler."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--jdk",
            default="adopt:1.11",
            advanced=True,
            help="The JDK to use for invoking javac."
            " This string will be passed directly to Coursier's `--jvm` parameter."
            " Run `cs java --available` to see a list of available JVM versions on your platform.",
        )


@dataclass(frozen=True)
class CompileJavaSourceRequest:
    target: Target


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

    lockfile, direct_deps = await MultiGet(
        Get(CoursierResolvedLockfile, CoursierLockfileForTargetRequest(Targets((request.target,)))),
        Get(Targets, DependenciesRequest(request.target.get(Dependencies))),
    )

    direct_dependency_classfiles = await MultiGet(
        Get(CompiledClassfiles, CompileJavaSourceRequest(target=target)) for target in direct_deps
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
                sources.snapshot.digest,
                prefixed_direct_dependency_classfiles_digest,
                materialized_classpath.digest,
                javac_binary.digest,
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
                *sources.files,
            ],
            input_digest=merged_digest,
            output_directories=("classfiles",),
            description=f"Compile {request.target.address.spec} with javac",
            level=LogLevel.DEBUG,
        ),
    )
    stripped_classfiles_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, "classfiles")
    )
    return CompiledClassfiles(digest=stripped_classfiles_digest)


def rules():
    return [
        *collect_rules(),
    ]
