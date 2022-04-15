# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os
import pkgutil
from dataclasses import dataclass

from pants.backend.kotlin.subsystems.kotlin import DEFAULT_KOTLIN_VERSION
from pants.core.util_rules.source_files import SourceFiles
from pants.engine.fs import CreateDigest, DigestContents, Directory, FileContent
from pants.engine.internals.native_engine import AddPrefix, Digest, MergeDigests, RemovePrefix
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, ProcessExecutionFailure, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.jvm.compile import ClasspathEntry
from pants.jvm.jdk_rules import InternalJdk, JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.resolve.common import ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.option.global_options import ProcessCleanupOption
from pants.util.logging import LogLevel

_KOTLIN_PARSER_ARTIFACT_REQUIREMENTS = ArtifactRequirements.from_coordinates(
    [
        Coordinate(
            group="org.jetbrains.kotlin",
            artifact="kotlin-compiler",
            version=DEFAULT_KOTLIN_VERSION,  # TODO: Make this follow the resolve?
        ),
        Coordinate(
            group="org.jetbrains.kotlin",
            artifact="kotlin-stdlib",
            version=DEFAULT_KOTLIN_VERSION,  # TODO: Make this follow the resolve?
        ),
        Coordinate(
            group="com.google.code.gson",
            artifact="gson",
            version="2.9.0",
        ),
    ]
)


@dataclass(frozen=True)
class KotlinImport:
    name: str
    alias: str | None
    is_wildcard: bool

    @classmethod
    def from_json_dict(cls, d: dict) -> KotlinImport:
        return cls(
            name=d["name"],
            alias=d.get("alias"),
            is_wildcard=d["isWildcard"],
        )


@dataclass(frozen=True)
class KotlinSourceDependencyAnalysis:
    imports: frozenset[KotlinImport]
    named_declarations: frozenset[str]

    @classmethod
    def from_json_dict(cls, d: dict) -> KotlinSourceDependencyAnalysis:
        return cls(
            imports=frozenset(KotlinImport.from_json_dict(i) for i in d["imports"]),
            named_declarations=frozenset(d["namedDeclarations"]),
        )


@dataclass(frozen=True)
class FallibleKotlinSourceDependencyAnalysisResult:
    process_result: FallibleProcessResult


class KotlinParserCompiledClassfiles(ClasspathEntry):
    pass


@rule(level=LogLevel.DEBUG)
async def analyze_kotlin_source_dependencies(
    processor_classfiles: KotlinParserCompiledClassfiles,
    source_files: SourceFiles,
) -> FallibleKotlinSourceDependencyAnalysisResult:
    # Use JDK 8 due to https://youtrack.jetbrains.com/issue/KTIJ-17192 and https://youtrack.jetbrains.com/issue/KT-37446.
    request = JdkRequest("adopt:8")
    env = await Get(JdkEnvironment, JdkRequest, request)
    jdk = InternalJdk(env._digest, env.nailgun_jar, env.coursier, env.jre_major_version)

    if len(source_files.files) > 1:
        raise ValueError(
            f"analyze_kotlin_source_dependencies expects sources with exactly 1 source file, but found {len(source_files.snapshot.files)}."
        )
    elif len(source_files.files) == 0:
        raise ValueError(
            "analyze_kotlin_source_dependencies expects sources with exactly 1 source file, but found none."
        )
    source_prefix = "__source_to_analyze"
    source_path = os.path.join(source_prefix, source_files.files[0])
    processorcp_relpath = "__processorcp"
    toolcp_relpath = "__toolcp"

    (tool_classpath, prefixed_source_files_digest,) = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(artifact_requirements=_KOTLIN_PARSER_ARTIFACT_REQUIREMENTS),
        ),
        Get(Digest, AddPrefix(source_files.snapshot.digest, source_prefix)),
    )

    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
        processorcp_relpath: processor_classfiles.digest,
    }

    analysis_output_path = "__source_analysis.json"

    process_result = await Get(
        FallibleProcessResult,
        JvmProcess(
            jdk=jdk,
            classpath_entries=[
                *tool_classpath.classpath_entries(toolcp_relpath),
                processorcp_relpath,
            ],
            argv=[
                "org.pantsbuild.backend.kotlin.dependency_inference.KotlinParserKt",
                analysis_output_path,
                source_path,
            ],
            input_digest=prefixed_source_files_digest,
            extra_immutable_input_digests=extra_immutable_input_digests,
            output_files=(analysis_output_path,),
            extra_nailgun_keys=extra_immutable_input_digests,
            description=f"Analyzing {source_files.files[0]}",
            level=LogLevel.DEBUG,
        ),
    )

    return FallibleKotlinSourceDependencyAnalysisResult(process_result=process_result)


@rule(level=LogLevel.DEBUG)
async def resolve_fallible_result_to_analysis(
    fallible_result: FallibleKotlinSourceDependencyAnalysisResult,
    process_cleanup: ProcessCleanupOption,
) -> KotlinSourceDependencyAnalysis:
    # TODO(#12725): Just convert directly to a ProcessResult like this:
    # result = await Get(ProcessResult, FallibleProcessResult, fallible_result.process_result)
    if fallible_result.process_result.exit_code == 0:
        analysis_contents = await Get(
            DigestContents, Digest, fallible_result.process_result.output_digest
        )
        analysis = json.loads(analysis_contents[0].content)
        return KotlinSourceDependencyAnalysis.from_json_dict(analysis)
    raise ProcessExecutionFailure(
        fallible_result.process_result.exit_code,
        fallible_result.process_result.stdout,
        fallible_result.process_result.stderr,
        "Kotlin source dependency analysis failed.",
        process_cleanup=process_cleanup.val,
    )


@rule
async def setup_kotlin_parser_classfiles(jdk: InternalJdk) -> KotlinParserCompiledClassfiles:
    dest_dir = "classfiles"

    parser_source_content = pkgutil.get_data(
        "pants.backend.kotlin.dependency_inference", "KotlinParser.kt"
    )
    if not parser_source_content:
        raise AssertionError("Unable to find KotlinParser.kt resource.")

    parser_source = FileContent("KotlinParser.kt", parser_source_content)

    tool_classpath, parser_classpath, source_digest = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(
                prefix="__toolcp",
                artifact_requirements=ArtifactRequirements.from_coordinates(
                    [
                        Coordinate(
                            group="org.jetbrains.kotlin",
                            artifact="kotlin-compiler",
                            version=DEFAULT_KOTLIN_VERSION,  # TODO: Pull from resolve or hard-code Kotlin version?
                        ),
                    ]
                ),
            ),
        ),
        Get(
            ToolClasspath,
            ToolClasspathRequest(
                prefix="__parsercp", artifact_requirements=_KOTLIN_PARSER_ARTIFACT_REQUIREMENTS
            ),
        ),
        Get(Digest, CreateDigest([parser_source, Directory(dest_dir)])),
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                tool_classpath.digest,
                parser_classpath.digest,
                source_digest,
            )
        ),
    )

    process_result = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            classpath_entries=tool_classpath.classpath_entries(),
            argv=[
                "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
                "-classpath",
                ":".join(parser_classpath.classpath_entries()),
                "-d",
                dest_dir,
                parser_source.path,
            ],
            input_digest=merged_digest,
            output_directories=(dest_dir,),
            description="Compile Kotlin parser for dependency inference with kotlinc",
            level=LogLevel.DEBUG,
            # NB: We do not use nailgun for this process, since it is launched exactly once.
            use_nailgun=False,
        ),
    )
    stripped_classfiles_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, dest_dir)
    )
    return KotlinParserCompiledClassfiles(digest=stripped_classfiles_digest)


def rules():
    return collect_rules()
