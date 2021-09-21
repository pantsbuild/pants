# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

import pkg_resources

from pants.backend.java.compile.javac import CompiledClassfiles
from pants.backend.java.compile.javac_binary import JavacBinary
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests, RemovePrefix
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirements,
    Coordinate,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


_LAUNCHER_BASENAME = "PantsJavaParserLauncher.java"


def _load_javaparser_launcher_source() -> bytes:
    return pkg_resources.resource_string(__name__, _LAUNCHER_BASENAME)


def java_parser_artifact_requirements() -> ArtifactRequirements:
    return ArtifactRequirements(
        [
            Coordinate(
                group="com.fasterxml.jackson.core", artifact="jackson-databind", version="2.12.4"
            ),
            Coordinate(
                group="com.github.javaparser",
                artifact="javaparser-symbol-solver-core",
                version="3.23.0",
            ),
        ],
    )


class JavaParserCompiledClassfiles(CompiledClassfiles):
    pass


@rule
async def build_processors(bash: BashBinary, javac: JavacBinary) -> JavaParserCompiledClassfiles:
    materialized_classpath = await Get(
        MaterializedClasspath,
        MaterializedClasspathRequest(
            prefix="__toolcp",
            artifact_requirements=(java_parser_artifact_requirements(),),
        ),
    )

    source_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    path=_LAUNCHER_BASENAME,
                    content=_load_javaparser_launcher_source(),
                )
            ]
        ),
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                materialized_classpath.digest,
                javac.digest,
                source_digest,
            )
        ),
    )

    process_result = await Get(
        ProcessResult,
        Process(
            argv=[
                bash.path,
                javac.javac_wrapper_script,
                "-cp",
                materialized_classpath.classpath_arg(),
                "-d",
                "classfiles",
                _LAUNCHER_BASENAME,
            ],
            input_digest=merged_digest,
            output_directories=("classfiles",),
            description=f"Compile {_LAUNCHER_BASENAME} import processors with javac",
            level=LogLevel.DEBUG,
        ),
    )
    stripped_classfiles_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, "classfiles")
    )
    return JavaParserCompiledClassfiles(digest=stripped_classfiles_digest)


def rules():
    return [
        *collect_rules(),
    ]
