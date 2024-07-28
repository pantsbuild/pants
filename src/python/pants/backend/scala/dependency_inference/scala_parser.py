# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.util_rules.versions import (
    ScalaArtifactsForVersionRequest,
    ScalaArtifactsForVersionResult,
    ScalaVersion,
    _resolve_scala_artifacts_for_version,
)
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
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
from pants.engine.process import FallibleProcessResult, ProcessResult, ProductDescription
from pants.engine.rules import collect_rules, rule
from pants.engine.target import WrappedTarget, WrappedTargetRequest
from pants.engine.unions import UnionRule
from pants.jvm.compile import ClasspathEntry
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.common import ArtifactRequirements
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, JvmToolBase
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.resources import read_resource

logger = logging.getLogger(__name__)


_PARSER_SCALA_VERSION = ScalaVersion.parse("2.13.8")
_PARSER_SCALA_BINARY_VERSION = _PARSER_SCALA_VERSION.binary


class ScalaParser(JvmToolBase):
    options_scope = "scala_parser"
    help = "Internal tool for parsing Scala sources to identify dependencies"

    default_artifacts = (
        f"org.scalameta:scalameta_{_PARSER_SCALA_BINARY_VERSION}:4.8.7",
        f"io.circe:circe-generic_{_PARSER_SCALA_BINARY_VERSION}:0.14.1",
        _resolve_scala_artifacts_for_version(
            _PARSER_SCALA_VERSION
        ).library_coordinate.to_coord_str(),
    )
    default_lockfile_resource = (
        "pants.backend.scala.dependency_inference",
        "scala_parser.lock",
    )


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
class ScalaProvidedSymbol:
    name: str
    recursive: bool

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]):
        return cls(name=data["name"], recursive=data["recursive"])

    def to_debug_json_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "recursive": self.recursive,
        }


@dataclass(frozen=True)
class ScalaConsumedSymbol:
    name: str
    is_absolute: bool

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]):
        return cls(name=data["name"], is_absolute=data["isAbsolute"])

    @property
    def is_qualified(self) -> bool:
        # TODO: Similar to #13545: we assume that a symbol containing a dot might already
        # be fully qualified.
        return "." in self.name

    def split(self) -> tuple[str, str]:
        """Splits the symbol name in its relative prefix and the rest of the symbol name."""
        symbol_rel_prefix, _, symbol_rel_suffix = self.name.partition(".")
        return (symbol_rel_prefix, symbol_rel_suffix)

    def to_debug_json_dict(self) -> dict[str, Any]:
        return {"name": self.name, "isAbsolute": self.is_absolute}


@dataclass(frozen=True)
class ScalaSourceDependencyAnalysis:
    provided_symbols: FrozenOrderedSet[ScalaProvidedSymbol]
    provided_symbols_encoded: FrozenOrderedSet[ScalaProvidedSymbol]
    imports_by_scope: FrozenDict[str, tuple[ScalaImport, ...]]
    _consumed_symbols_by_scope: FrozenDict[str, FrozenOrderedSet[ScalaConsumedSymbol]]
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

        for consumption_scope, consumed_symbols in self._consumed_symbols_by_scope.items():
            parent_scopes = tuple(scope_and_parents(consumption_scope))
            for symbol in consumed_symbols:
                if not self.scopes or symbol.is_qualified or symbol.is_absolute:
                    yield symbol.name

                if symbol.is_absolute:
                    # We do not need to qualify this symbol any further as we know its
                    # name is the actual fully qualified name
                    continue

                for parent_scope in parent_scopes:
                    if parent_scope in self.scopes:
                        # A package declaration is a parent of this scope, and any of its symbols
                        # could be in scope.
                        yield f"{parent_scope}.{symbol.name}"

                    for imp in self.imports_by_scope.get(parent_scope, ()):
                        if imp.is_wildcard:
                            # There is a wildcard import in a parent scope.
                            yield f"{imp.name}.{symbol.name}"
                        if symbol.is_qualified:
                            # If the parent scope has an import which defines the first token of the
                            # symbol, then it might be a relative usage of an import.
                            symbol_rel_prefix, symbol_rel_suffix = symbol.split()
                            if imp.alias:
                                if imp.alias == symbol_rel_prefix:
                                    yield f"{imp.name}.{symbol_rel_suffix}"
                            elif imp.name.endswith(f".{symbol_rel_prefix}"):
                                yield f"{imp.name}.{symbol_rel_suffix}"

    @property
    def consumed_symbols_by_scope(self) -> FrozenDict[str, FrozenOrderedSet[str]]:
        return FrozenDict(
            {
                key: FrozenOrderedSet(v.name for v in values)
                for key, values in self._consumed_symbols_by_scope.items()
            }
        )

    @classmethod
    def from_json_dict(cls, d: dict) -> ScalaSourceDependencyAnalysis:
        return cls(
            provided_symbols=FrozenOrderedSet(
                ScalaProvidedSymbol.from_json_dict(v) for v in d["providedSymbols"]
            ),
            provided_symbols_encoded=FrozenOrderedSet(
                ScalaProvidedSymbol.from_json_dict(v) for v in d["providedSymbolsEncoded"]
            ),
            imports_by_scope=FrozenDict(
                {
                    key: tuple(ScalaImport.from_json_dict(v) for v in values)
                    for key, values in d["importsByScope"].items()
                }
            ),
            _consumed_symbols_by_scope=FrozenDict(
                {
                    key: FrozenOrderedSet(ScalaConsumedSymbol.from_json_dict(v) for v in values)
                    for key, values in d["consumedSymbolsByScope"].items()
                }
            ),
            scopes=FrozenOrderedSet(d["scopes"]),
        )

    def to_debug_json_dict(self) -> dict[str, Any]:
        return {
            "provided_symbols": [v.to_debug_json_dict() for v in self.provided_symbols],
            "provided_symbols_encoded": [
                v.to_debug_json_dict() for v in self.provided_symbols_encoded
            ],
            "imports_by_scope": {
                key: [v.to_debug_json_dict() for v in values]
                for key, values in self.imports_by_scope.items()
            },
            "consumed_symbols_by_scope": {
                key: [v.to_debug_json_dict() for v in values]
                for key, values in self._consumed_symbols_by_scope.items()
            },
            "scopes": list(self.scopes),
        }


@dataclass(frozen=True)
class FallibleScalaSourceDependencyAnalysisResult:
    process_result: FallibleProcessResult


class ScalaParserCompiledClassfiles(ClasspathEntry):
    pass


@dataclass(frozen=True)
class AnalyzeScalaSourceRequest:
    source_files: SourceFiles
    scala_version: ScalaVersion
    source3: bool


@rule(level=LogLevel.DEBUG)
async def create_analyze_scala_source_request(
    scala_subsystem: ScalaSubsystem, jvm: JvmSubsystem, scalac: Scalac, request: SourceFilesRequest
) -> AnalyzeScalaSourceRequest:
    address = request.sources_fields[0].address

    wrapped_tgt, source_files = await MultiGet(
        Get(
            WrappedTarget,
            WrappedTargetRequest(
                address, description_of_origin="<the Scala analyze request setup rule>"
            ),
        ),
        Get(SourceFiles, SourceFilesRequest, request),
    )

    tgt = wrapped_tgt.target
    resolve = tgt[JvmResolveField].normalized_value(jvm)
    scala_version = scala_subsystem.version_for_resolve(resolve)
    source3 = "-Xsource:3" in scalac.args

    return AnalyzeScalaSourceRequest(source_files, scala_version, source3)


@rule(level=LogLevel.DEBUG)
async def analyze_scala_source_dependencies(
    jdk: InternalJdk,
    processor_classfiles: ScalaParserCompiledClassfiles,
    tool: ScalaParser,
    request: AnalyzeScalaSourceRequest,
) -> FallibleScalaSourceDependencyAnalysisResult:
    source_files = request.source_files

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

    tool_classpath, prefixed_source_files_digest = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(lockfile=GenerateJvmLockfileFromTool.create(tool)),
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
                str(request.scala_version),
                str(request.source3),
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
) -> ScalaSourceDependencyAnalysis:
    description = ProductDescription("Scala source dependency analysis failed.")
    result = await Get(
        ProcessResult,
        {
            fallible_result.process_result: FallibleProcessResult,
            description: ProductDescription,
        },
    )
    analysis_contents = await Get(DigestContents, Digest, result.output_digest)
    analysis = json.loads(analysis_contents[0].content)
    return ScalaSourceDependencyAnalysis.from_json_dict(analysis)


# TODO(13879): Consolidate compilation of wrapper binaries to common rules.
@rule
async def setup_scala_parser_classfiles(
    jdk: InternalJdk, tool: ScalaParser
) -> ScalaParserCompiledClassfiles:
    dest_dir = "classfiles"

    parser_source_content = read_resource(
        "pants.backend.scala.dependency_inference", "ScalaParser.scala"
    )
    if not parser_source_content:
        raise AssertionError("Unable to find ScalaParser.scala resource.")

    parser_source = FileContent("ScalaParser.scala", parser_source_content)

    scala_artifacts = Get(
        ScalaArtifactsForVersionResult, ScalaArtifactsForVersionRequest(_PARSER_SCALA_VERSION)
    )

    tool_classpath, parser_classpath, source_digest = await MultiGet(
        Get(
            ToolClasspath,
            ToolClasspathRequest(
                prefix="__toolcp",
                artifact_requirements=ArtifactRequirements.from_coordinates(
                    scala_artifacts.all_coordinates
                ),
            ),
        ),
        Get(
            ToolClasspath,
            ToolClasspathRequest(
                prefix="__parsercp", lockfile=(GenerateJvmLockfileFromTool.create(tool))
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


def rules():
    return (
        *collect_rules(),
        *jdk_rules(),
        UnionRule(ExportableTool, ScalaParser),
    )
