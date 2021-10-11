# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.java.dependency_inference.types import JavaSourceDependencyAnalysis
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.collection import DeduplicatedCollection
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import SourcesField


class ParsedJavaImports(DeduplicatedCollection[str]):
    """All the discovered imports from a Java source file."""

    sort_input = True


@dataclass(frozen=True)
class ParseJavaImportsRequest:
    sources: SourcesField


@rule
async def parse_java_imports(request: ParseJavaImportsRequest) -> ParsedJavaImports:
    source_files = await Get(SourceFiles, SourceFilesRequest([request.sources]))
    analysis = await Get(JavaSourceDependencyAnalysis, SourceFiles, source_files)
    return ParsedJavaImports(imp.name for imp in analysis.imports)


def rules():
    return collect_rules()
