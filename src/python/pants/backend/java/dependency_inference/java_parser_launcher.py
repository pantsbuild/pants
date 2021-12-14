# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

import pkg_resources

from pants.engine.fs import CreateDigest, Digest, Directory, FileContent, MergeDigests, RemovePrefix
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.jvm.jdk_rules import JdkSetup
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
    # Update in concert with the target definition for `java_parser`.
    return ArtifactRequirements.from_coordinates(
        [
            Coordinate(
                group="com.fasterxml.jackson.core", artifact="jackson-databind", version="2.12.4"
            ),
            Coordinate(
                group="com.fasterxml.jackson.datatype",
                artifact="jackson-datatype-jdk8",
                version="2.12.4",
            ),
            Coordinate(
                group="com.github.javaparser",
                artifact="javaparser-symbol-solver-core",
                version="3.23.0",
            ),
        ],
    )


@dataclass(frozen=True)
class JavaParserCompiledClassfiles:
    digest: Digest


# TODO(13879): Consolidate compilation of wrapper binaries to common rules.
@rule
async def build_processors(bash: BashBinary, jdk_setup: JdkSetup) -> JavaParserCompiledClassfiles:
    dest_dir = "classfiles"

    materialized_classpath, source_digest = await MultiGet(
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                prefix="__toolcp",
                artifact_requirements=(java_parser_artifact_requirements(),),
            ),
        ),
        Get(
            Digest,
            CreateDigest(
                [
                    FileContent(
                        path=_LAUNCHER_BASENAME,
                        content=_load_javaparser_launcher_source(),
                    ),
                    Directory(dest_dir),
                ]
            ),
        ),
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                materialized_classpath.digest,
                source_digest,
            )
        ),
    )

    # NB: We do not use nailgun for this process, since it is launched exactly once.
    process_result = await Get(
        ProcessResult,
        Process(
            argv=[
                *jdk_setup.args(bash, [f"{jdk_setup.java_home}/lib/tools.jar"]),
                "com.sun.tools.javac.Main",
                "-cp",
                ":".join(materialized_classpath.classpath_entries()),
                "-d",
                dest_dir,
                _LAUNCHER_BASENAME,
            ],
            input_digest=merged_digest,
            append_only_caches=jdk_setup.append_only_caches,
            immutable_input_digests=jdk_setup.immutable_input_digests,
            env=jdk_setup.env,
            output_directories=(dest_dir,),
            description=f"Compile {_LAUNCHER_BASENAME} import processors with javac",
            level=LogLevel.DEBUG,
        ),
    )
    stripped_classfiles_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, dest_dir)
    )
    return JavaParserCompiledClassfiles(digest=stripped_classfiles_digest)


def rules():
    return [
        *collect_rules(),
    ]
