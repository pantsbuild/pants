# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterator

from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE, GenerateToolLockfileSentinel
from pants.core.util_rules.source_files import SourceFiles
from pants.engine.fs import CreateDigest, DigestContents, Directory, FileContent
from pants.engine.internals.native_engine import AddPrefix, Digest, MergeDigests, RemovePrefix
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, ProcessExecutionFailure, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.compile import ClasspathEntry
from pants.jvm.jdk_rules import InternalJdk, JdkEnvironment, JdkRequest, JvmProcess
from pants.jvm.resolve.common import ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, GenerateJvmToolLockfileSentinel
from pants.option.global_options import KeepSandboxes
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.resources import read_resource

_PARSER_KOTLIN_VERSION = "1.6.20"


class KotlinParserToolLockfileSentinel(GenerateJvmToolLockfileSentinel):
    resolve_name = "kotlin-parser"


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

    def to_debug_json_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "alias": self.alias,
            "is_wildcard": self.is_wildcard,
        }


@dataclass(frozen=True)
class KotlinSourceDependencyAnalysis:
    package: str
    imports: frozenset[KotlinImport]
    named_declarations: frozenset[str]
    consumed_symbols_by_scope: FrozenDict[str, frozenset[str]]
    scopes: frozenset[str]

    def fully_qualified_consumed_symbols(self) -> Iterator[str]:
        """Consumed symbols qualified in various ways.

        This method _will_ introduce false-positives, because we will assume that the symbol could
        have been provided by any wildcard import in scope, as well as being declared in the current
        package.
        """

        def scope_and_parents(scope: str) -> Iterator[str]:
            while True:
                yield scope
                if scope == "":
                    break
                scope, _, _ = scope.rpartition(".")

        for consumption_scope, consumed_symbols in self.consumed_symbols_by_scope.items():
            parent_scopes = tuple(scope_and_parents(consumption_scope))
            for symbol in consumed_symbols:
                symbol_rel_prefix, dot_in_symbol, symbol_rel_suffix = symbol.partition(".")
                if not self.scopes or dot_in_symbol:
                    # TODO: Similar to #13545: we assume that a symbol containing a dot might already
                    # be fully qualified.
                    yield symbol
                for parent_scope in parent_scopes:
                    if parent_scope in self.scopes:
                        # A package declaration is a parent of this scope, and any of its symbols
                        # could be in scope.
                        yield f"{parent_scope}.{symbol}"

                    for imp in self.imports if parent_scope == self.package else ():
                        if imp.is_wildcard:
                            # There is a wildcard import in a parent scope.
                            yield f"{imp.name}.{symbol}"
                        if dot_in_symbol:
                            # If the parent scope has an import which defines the first token of the
                            # symbol, then it might be a relative usage of an import.
                            if imp.alias:
                                if imp.alias == symbol_rel_prefix:
                                    yield f"{imp.name}.{symbol_rel_suffix}"
                            elif imp.name.endswith(f".{symbol_rel_prefix}"):
                                yield f"{imp.name}.{symbol_rel_suffix}"

    @classmethod
    def from_json_dict(cls, d: dict) -> KotlinSourceDependencyAnalysis:
        return cls(
            package=d["package"],
            imports=frozenset(KotlinImport.from_json_dict(i) for i in d["imports"]),
            named_declarations=frozenset(d["namedDeclarations"]),
            consumed_symbols_by_scope=FrozenDict(
                {k: frozenset(v) for k, v in d["consumedSymbolsByScope"].items()}
            ),
            scopes=frozenset(d["scopes"]),
        )

    def to_debug_json_dict(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "imports": [imp.to_debug_json_dict() for imp in self.imports],
            "named_declarations": list(self.named_declarations),
            "consumed_symbols_by_scope": {
                k: sorted(v) for k, v in self.consumed_symbols_by_scope.items()
            },
            "scopes": list(self.scopes),
        }


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
    jdk = InternalJdk.from_jdk_environment(env)

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

    parser_lockfile_request = await Get(
        GenerateJvmLockfileFromTool, KotlinParserToolLockfileSentinel()
    )
    (
        tool_classpath,
        prefixed_source_files_digest,
    ) = await MultiGet(
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
    keep_sandboxes: KeepSandboxes,
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
        keep_sandboxes=keep_sandboxes,
    )


@rule
async def setup_kotlin_parser_classfiles(jdk: InternalJdk) -> KotlinParserCompiledClassfiles:
    dest_dir = "classfiles"

    parser_source_content = read_resource(
        "pants.backend.kotlin.dependency_inference", "KotlinParser.kt"
    )
    if not parser_source_content:
        raise AssertionError("Unable to find KotlinParser.kt resource.")

    parser_source = FileContent("KotlinParser.kt", parser_source_content)

    parser_lockfile_request = await Get(
        GenerateJvmLockfileFromTool, KotlinParserToolLockfileSentinel()
    )

    tool_classpath, parser_classpath, source_digest = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(
                prefix="__toolcp",
                artifact_requirements=ArtifactRequirements.from_coordinates(
                    [
                        Coordinate(
                            group="org.jetbrains.kotlin",
                            artifact="kotlin-compiler-embeddable",
                            version=_PARSER_KOTLIN_VERSION,  # TODO: Pull from resolve or hard-code Kotlin version?
                        ),
                    ]
                ),
            ),
        ),
        Get(
            ToolClasspath,
            ToolClasspathRequest(prefix="__parsercp", lockfile=parser_lockfile_request),
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


@rule
def generate_kotlin_parser_lockfile_request(
    _: KotlinParserToolLockfileSentinel,
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool(
        artifact_inputs=FrozenOrderedSet(
            {
                f"org.jetbrains.kotlin:kotlin-compiler:{_PARSER_KOTLIN_VERSION}",
                f"org.jetbrains.kotlin:kotlin-stdlib:{_PARSER_KOTLIN_VERSION}",
                "com.google.code.gson:gson:2.9.0",
            }
        ),
        artifact_option_name="n/a",
        lockfile_option_name="n/a",
        resolve_name=KotlinParserToolLockfileSentinel.resolve_name,
        read_lockfile_dest=DEFAULT_TOOL_LOCKFILE,
        write_lockfile_dest="src/python/pants/backend/kotlin/dependency_inference/kotlin_parser.lock",
        default_lockfile_resource=(
            "pants.backend.kotlin.dependency_inference",
            "kotlin_parser.lock",
        ),
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateToolLockfileSentinel, KotlinParserToolLockfileSentinel),
    )
