# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os.path
from dataclasses import dataclass

import pkg_resources

from pants.backend.java.dependency_inference.types import JavaSourceDependencyAnalysis
from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE, GenerateToolLockfileSentinel
from pants.core.util_rules.source_files import SourceFiles
from pants.engine.fs import AddPrefix, CreateDigest, Digest, DigestContents, Directory, FileContent
from pants.engine.internals.native_engine import MergeDigests, RemovePrefix
from pants.engine.process import FallibleProcessResult, ProcessExecutionFailure, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
from pants.option.global_options import ProcessCleanupOption
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


_LAUNCHER_BASENAME = "PantsJavaParserLauncher.java"


class JavaParserToolLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = "java-parser"


@dataclass(frozen=True)
class JavaSourceDependencyAnalysisRequest:
    source_files: SourceFiles


@dataclass(frozen=True)
class FallibleJavaSourceDependencyAnalysisResult:
    process_result: FallibleProcessResult


@dataclass(frozen=True)
class JavaParserCompiledClassfiles:
    digest: Digest


@rule(level=LogLevel.DEBUG)
async def resolve_fallible_result_to_analysis(
    fallible_result: FallibleJavaSourceDependencyAnalysisResult,
    process_cleanup: ProcessCleanupOption,
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
        process_cleanup=process_cleanup.val,
    )


@rule(level=LogLevel.DEBUG)
async def make_analysis_request_from_source_files(
    source_files: SourceFiles,
) -> JavaSourceDependencyAnalysisRequest:
    return JavaSourceDependencyAnalysisRequest(source_files=source_files)


@rule(level=LogLevel.DEBUG)
async def analyze_java_source_dependencies(
    processor_classfiles: JavaParserCompiledClassfiles,
    jdk: InternalJdk,
    request: JavaSourceDependencyAnalysisRequest,
) -> FallibleJavaSourceDependencyAnalysisResult:
    source_files = request.source_files
    if len(source_files.files) > 1:
        raise ValueError(
            f"parse_java_package expects sources with exactly 1 source file, but found {len(source_files.files)}."
        )
    elif len(source_files.files) == 0:
        raise ValueError(
            "parse_java_package expects sources with exactly 1 source file, but found none."
        )
    source_prefix = "__source_to_analyze"
    source_path = os.path.join(source_prefix, source_files.files[0])
    processorcp_relpath = "__processorcp"
    toolcp_relpath = "__toolcp"

    parser_lockfile_request = await Get(
        GenerateJvmLockfileFromTool, JavaParserToolLockfileSentinel()
    )
    tool_classpath, prefixed_source_files_digest = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(lockfile=parser_lockfile_request),
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
                "org.pantsbuild.javaparser.PantsJavaParserLauncher",
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

    return FallibleJavaSourceDependencyAnalysisResult(process_result=process_result)


def _load_javaparser_launcher_source() -> bytes:
    return pkg_resources.resource_string(__name__, _LAUNCHER_BASENAME)


# TODO(13879): Consolidate compilation of wrapper binaries to common rules.
@rule
async def build_processors(jdk: InternalJdk) -> JavaParserCompiledClassfiles:
    dest_dir = "classfiles"
    parser_lockfile_request = await Get(
        GenerateJvmLockfileFromTool, JavaParserToolLockfileSentinel()
    )
    materialized_classpath, source_digest = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(prefix="__toolcp", lockfile=parser_lockfile_request),
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

    process_result = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            classpath_entries=[f"{jdk.java_home}/lib/tools.jar"],
            argv=[
                "com.sun.tools.javac.Main",
                "-cp",
                ":".join(materialized_classpath.classpath_entries()),
                "-d",
                dest_dir,
                _LAUNCHER_BASENAME,
            ],
            input_digest=merged_digest,
            output_directories=(dest_dir,),
            description=f"Compile {_LAUNCHER_BASENAME} import processors with javac",
            level=LogLevel.DEBUG,
            # NB: We do not use nailgun for this process, since it is launched exactly once.
            use_nailgun=False,
        ),
    )
    stripped_classfiles_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, dest_dir)
    )
    return JavaParserCompiledClassfiles(digest=stripped_classfiles_digest)


@rule
def generate_java_parser_lockfile_request(
    _: JavaParserToolLockfileSentinel,
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool(
        artifact_inputs=FrozenOrderedSet(
            {
                "com.fasterxml.jackson.core:jackson-databind:2.12.4",
                "com.fasterxml.jackson.datatype:jackson-datatype-jdk8:2.12.4",
                "com.github.javaparser:javaparser-symbol-solver-core:3.23.0",
            }
        ),
        artifact_option_name="n/a",
        lockfile_option_name="n/a",
        resolve_name=JavaParserToolLockfileSentinel.resolve_name,
        read_lockfile_dest=DEFAULT_TOOL_LOCKFILE,
        write_lockfile_dest="src/python/pants/backend/java/dependency_inference/java_parser.lock",
        default_lockfile_resource=(
            "pants.backend.java.dependency_inference",
            "java_parser.lock",
        ),
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateToolLockfileSentinel, JavaParserToolLockfileSentinel),
    ]
