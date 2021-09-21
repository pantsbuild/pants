# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os.path
from dataclasses import dataclass

from pants.backend.java.dependency_inference.java_parser_launcher import (
    JavaParserCompiledClassfiles,
    java_parser_artifact_requirements,
)
from pants.backend.java.dependency_inference.types import JavaSourceDependencyAnalysis
from pants.backend.java.util_rules import JdkSetup
from pants.core.util_rules.source_files import SourceFiles
from pants.engine.fs import AddPrefix, Digest, DigestContents, MergeDigests
from pants.engine.process import FallibleProcessResult, Process, ProcessExecutionFailure
from pants.engine.rules import Get, collect_rules, rule
from pants.jvm.resolve.coursier_fetch import MaterializedClasspath, MaterializedClasspathRequest
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FallibleJavaSourceDependencyAnalysisResult:
    process_result: FallibleProcessResult


@rule(level=LogLevel.DEBUG)
async def resolve_fallible_result_to_analysis(
    fallible_result: FallibleJavaSourceDependencyAnalysisResult,
) -> JavaSourceDependencyAnalysis:
    # TODO(#12725): Just convert directly to a ProcessResult like this:
    # result = await Get(ProcessResult, FallibleProcessResult, fallible_result.process_result)
    if fallible_result.process_result.exit_code == 0:
        analysis_contents = await Get(
            DigestContents, Digest, fallible_result.process_result.output_digest
        )
        analysis = json.loads(analysis_contents[0].content)
        return JavaSourceDependencyAnalysis.from_json_dict(analysis)
    raise ProcessExecutionFailure(
        fallible_result.process_result.exit_code,
        fallible_result.process_result.stdout,
        fallible_result.process_result.stderr,
        "Java source dependency analysis failed.",
    )


@rule(level=LogLevel.DEBUG)
async def analyze_java_source_dependencies(
    jdk_setup: JdkSetup,
    processor_classfiles: JavaParserCompiledClassfiles,
    source_files: SourceFiles,
) -> FallibleJavaSourceDependencyAnalysisResult:
    if len(source_files.snapshot.files) > 1:
        raise ValueError(
            f"parse_java_package expects sources with exactly 1 source file, but found {len(source_files.snapshot.files)}."
        )
    elif len(source_files.snapshot.files) == 0:
        raise ValueError(
            "parse_java_package expects sources with exactly 1 source file, but found none."
        )
    source_prefix = "__source_to_analyze"
    source_path = os.path.join(source_prefix, source_files.snapshot.files[0])
    processorcp_relpath = "__processorcp"

    tool_classpath = await Get(
        MaterializedClasspath,
        MaterializedClasspathRequest(
            prefix="__toolcp",
            artifact_requirements=(java_parser_artifact_requirements(),),
        ),
    )
    prefixed_processor_classfiles_digest = await Get(
        Digest, AddPrefix(processor_classfiles.digest, processorcp_relpath)
    )
    prefixed_source_files_digest = await Get(
        Digest, AddPrefix(source_files.snapshot.digest, source_prefix)
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                prefixed_processor_classfiles_digest,
                tool_classpath.digest,
                prefixed_source_files_digest,
            )
        ),
    )

    analysis_output_path = "__source_analysis.json"

    proc = Process(
        argv=[
            f"{jdk_setup.java_home}/bin/java",
            "-cp",
            ":".join([tool_classpath.classpath_arg(), processorcp_relpath]),
            "org.pantsbuild.javaparser.PantsJavaParserLauncher",
            analysis_output_path,
            source_path,
        ],
        input_digest=merged_digest,
        output_files=(analysis_output_path,),
        description="Run Spoon analysis against Java source",
        level=LogLevel.DEBUG,
    )

    process_result = await Get(
        FallibleProcessResult,
        Process,
        proc,
    )

    return FallibleJavaSourceDependencyAnalysisResult(process_result=process_result)


def rules():
    return [
        *collect_rules(),
    ]
