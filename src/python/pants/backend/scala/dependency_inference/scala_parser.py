# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
import os
import pkgutil
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE, GenerateToolLockfileSentinel
from pants.core.util_rules.source_files import SourceFiles
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    Directory,
    FileContent,
    MergeDigests,
    RemovePrefix,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, ProcessExecutionFailure, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.compile import ClasspathEntry
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.common import ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
from pants.option.global_options import ProcessCleanupOption
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


_PARSER_SCALA_VERSION = "2.13.8"
_PARSER_SCALA_BINARY_VERSION = _PARSER_SCALA_VERSION.rpartition(".")[0]


class ScalaParserToolLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = "scala-parser"


@dataclass(frozen=True)
class ScalaImport:
    name: str
    alias: str | None
    is_wildcard: bool

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]):
        return cls(name=data["name"], alias=data.get("alias"), is_wildcard=data["isWildcard"])

    def to_debug_json_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "alias": self.alias,
            "is_wildcard": self.is_wildcard,
        }


@dataclass(frozen=True)
class ScalaSourceDependencyAnalysis:
    provided_symbols: FrozenOrderedSet[str]
    provided_symbols_encoded: FrozenOrderedSet[str]
    imports_by_scope: FrozenDict[str, tuple[ScalaImport, ...]]
    consumed_symbols_by_scope: FrozenDict[str, FrozenOrderedSet[str]]
    scopes: FrozenOrderedSet[str]

    def all_imports(self) -> Iterator[str]:
        # TODO: This might also be an import relative to its scope.
        for imports in self.imports_by_scope.values():
            for imp in imports:
                yield imp.name

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

                    for imp in self.imports_by_scope.get(parent_scope, ()):
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
    def from_json_dict(cls, d: dict) -> ScalaSourceDependencyAnalysis:
        return cls(
            provided_symbols=FrozenOrderedSet(d["providedSymbols"]),
            provided_symbols_encoded=FrozenOrderedSet(d["providedSymbolsEncoded"]),
            imports_by_scope=FrozenDict(
                {
                    key: tuple(ScalaImport.from_json_dict(v) for v in values)
                    for key, values in d["importsByScope"].items()
                }
            ),
            consumed_symbols_by_scope=FrozenDict(
                {
                    key: FrozenOrderedSet(values)
                    for key, values in d["consumedSymbolsByScope"].items()
                }
            ),
            scopes=FrozenOrderedSet(d["scopes"]),
        )

    def to_debug_json_dict(self) -> dict[str, Any]:
        return {
            "provided_symbols": list(self.provided_symbols),
            "provided_symbols_encoded": list(self.provided_symbols_encoded),
            "imports_by_scope": {
                key: [v.to_debug_json_dict() for v in values]
                for key, values in self.imports_by_scope.items()
            },
            "consumed_symbols_by_scope": {
                k: sorted(v) for k, v in self.consumed_symbols_by_scope.items()
            },
            "scopes": list(self.scopes),
        }


@dataclass(frozen=True)
class FallibleScalaSourceDependencyAnalysisResult:
    process_result: FallibleProcessResult


class ScalaParserCompiledClassfiles(ClasspathEntry):
    pass


@rule(level=LogLevel.DEBUG)
async def analyze_scala_source_dependencies(
    jdk: InternalJdk,
    processor_classfiles: ScalaParserCompiledClassfiles,
    source_files: SourceFiles,
) -> FallibleScalaSourceDependencyAnalysisResult:
    if len(source_files.files) > 1:
        raise ValueError(
            f"analyze_scala_source_dependencies expects sources with exactly 1 source file, but found {len(source_files.snapshot.files)}."
        )
    elif len(source_files.files) == 0:
        raise ValueError(
            "analyze_scala_source_dependencies expects sources with exactly 1 source file, but found none."
        )
    source_prefix = "__source_to_analyze"
    source_path = os.path.join(source_prefix, source_files.files[0])
    processorcp_relpath = "__processorcp"
    toolcp_relpath = "__toolcp"

    parser_lockfile_request = await Get(
        GenerateJvmLockfileFromTool, ScalaParserToolLockfileSentinel()
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
                "org.pantsbuild.backend.scala.dependency_inference.ScalaParser",
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

    return FallibleScalaSourceDependencyAnalysisResult(process_result=process_result)


@rule(level=LogLevel.DEBUG)
async def resolve_fallible_result_to_analysis(
    fallible_result: FallibleScalaSourceDependencyAnalysisResult,
    process_cleanup: ProcessCleanupOption,
) -> ScalaSourceDependencyAnalysis:
    # TODO(#12725): Just convert directly to a ProcessResult like this:
    # result = await Get(ProcessResult, FallibleProcessResult, fallible_result.process_result)
    if fallible_result.process_result.exit_code == 0:
        analysis_contents = await Get(
            DigestContents, Digest, fallible_result.process_result.output_digest
        )
        analysis = json.loads(analysis_contents[0].content)
        return ScalaSourceDependencyAnalysis.from_json_dict(analysis)
    raise ProcessExecutionFailure(
        fallible_result.process_result.exit_code,
        fallible_result.process_result.stdout,
        fallible_result.process_result.stderr,
        "Scala source dependency analysis failed.",
        process_cleanup=process_cleanup.val,
    )


# TODO(13879): Consolidate compilation of wrapper binaries to common rules.
@rule
async def setup_scala_parser_classfiles(jdk: InternalJdk) -> ScalaParserCompiledClassfiles:
    dest_dir = "classfiles"

    parser_source_content = pkgutil.get_data(
        "pants.backend.scala.dependency_inference", "ScalaParser.scala"
    )
    if not parser_source_content:
        raise AssertionError("Unable to find ScalaParser.scala resource.")

    parser_source = FileContent("ScalaParser.scala", parser_source_content)

    parser_lockfile_request = await Get(
        GenerateJvmLockfileFromTool, ScalaParserToolLockfileSentinel()
    )

    tool_classpath, parser_classpath, source_digest = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(
                prefix="__toolcp",
                artifact_requirements=ArtifactRequirements.from_coordinates(
                    [
                        Coordinate(
                            group="org.scala-lang",
                            artifact="scala-compiler",
                            version=_PARSER_SCALA_VERSION,
                        ),
                        Coordinate(
                            group="org.scala-lang",
                            artifact="scala-library",
                            version=_PARSER_SCALA_VERSION,
                        ),
                        Coordinate(
                            group="org.scala-lang",
                            artifact="scala-reflect",
                            version=_PARSER_SCALA_VERSION,
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
                "scala.tools.nsc.Main",
                "-bootclasspath",
                ":".join(tool_classpath.classpath_entries()),
                "-classpath",
                ":".join(parser_classpath.classpath_entries()),
                "-d",
                dest_dir,
                parser_source.path,
            ],
            input_digest=merged_digest,
            output_directories=(dest_dir,),
            description="Compile Scala parser for dependency inference with scalac",
            level=LogLevel.DEBUG,
            # NB: We do not use nailgun for this process, since it is launched exactly once.
            use_nailgun=False,
        ),
    )
    stripped_classfiles_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, dest_dir)
    )
    return ScalaParserCompiledClassfiles(digest=stripped_classfiles_digest)


@rule
def generate_scala_parser_lockfile_request(
    _: ScalaParserToolLockfileSentinel,
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool(
        artifact_inputs=FrozenOrderedSet(
            {
                f"org.scalameta:scalameta_{_PARSER_SCALA_BINARY_VERSION}:4.4.30",
                f"io.circe:circe-generic_{_PARSER_SCALA_BINARY_VERSION}:0.14.1",
                f"org.scala-lang:scala-library:{_PARSER_SCALA_VERSION}",
            }
        ),
        artifact_option_name="n/a",
        lockfile_option_name="n/a",
        resolve_name=ScalaParserToolLockfileSentinel.resolve_name,
        read_lockfile_dest=DEFAULT_TOOL_LOCKFILE,
        write_lockfile_dest="src/python/pants/backend/scala/dependency_inference/scala_parser.lock",
        default_lockfile_resource=(
            "pants.backend.scala.dependency_inference",
            "scala_parser.lock",
        ),
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateToolLockfileSentinel, ScalaParserToolLockfileSentinel),
    )
