# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.python.dependency_inference.subsystem import PythonInferSubsystem
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.util_rules.source_files import SourceFiles
from pants.core.util_rules.stripped_source_files import strip_source_roots
from pants.engine.collection import DeduplicatedCollection
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.native_engine import NativeDependenciesRequest
from pants.engine.intrinsics import create_digest, parse_python_deps
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.resources import read_resource

logger = logging.getLogger(__name__)


@dataclass(frozen=True, order=True)
class ParsedPythonImportInfo:
    lineno: int
    # An import is considered "weak" if we're unsure if a dependency will exist between the parsed
    # file and the parsed import.
    # Examples of "weak" imports include string imports (if enabled) or those inside a try block
    # which has a handler catching ImportError.
    weak: bool


class ParsedPythonImports(FrozenDict[str, ParsedPythonImportInfo]):
    """All the discovered imports from a Python source file mapped to the relevant info."""


class ParsedPythonAssetPaths(DeduplicatedCollection[str]):
    """All the discovered possible assets from a Python source file."""

    # N.B. Don't set `sort_input`, as the input is already sorted


# TODO: Use the Native* eqivalents of these classes directly? Would require
#  conversion to the component classes in Rust code. Might require passing
#  the PythonInferSubsystem settings through to Rust and acting on them there.


@dataclass(frozen=True)
class PythonFileDependencies:
    imports: ParsedPythonImports
    assets: ParsedPythonAssetPaths


@dataclass(frozen=True)
class PythonFilesDependencies:
    path_to_deps: FrozenDict[str, PythonFileDependencies]


@dataclass(frozen=True)
class ParsePythonDependenciesRequest:
    source: SourceFiles
    interpreter_constraints: InterpreterConstraints


@dataclass(frozen=True)
class PythonDependencyVisitor:
    """Wraps a subclass of DependencyVisitorBase."""

    digest: Digest  # The file contents for the visitor
    classname: str  # The full classname, e.g., _my_custom_dep_parser.MyCustomVisitor
    env: FrozenDict[str, str]  # Set these env vars when invoking the visitor


@dataclass(frozen=True)
class ParserScript:
    digest: Digest
    env: FrozenDict[str, str]


_scripts_package = "pants.backend.python.dependency_inference.scripts"


async def get_scripts_digest(scripts_package: str, filenames: Iterable[str]) -> Digest:
    scripts = [read_resource(scripts_package, filename) for filename in filenames]
    assert all(script is not None for script in scripts)
    path_prefix = scripts_package.replace(".", os.path.sep)
    contents = [
        FileContent(os.path.join(path_prefix, relpath), script)
        for relpath, script in zip(filenames, scripts)
    ]

    # Python 2 requires all the intermediate __init__.py to exist in the sandbox.
    package = scripts_package
    while package:
        contents.append(
            FileContent(
                os.path.join(package.replace(".", os.path.sep), "__init__.py"),
                read_resource(package, "__init__.py"),
            )
        )
        package = package.rpartition(".")[0]

    digest = await create_digest(CreateDigest(contents))
    return digest


@rule(level=LogLevel.DEBUG)
async def parse_python_dependencies(
    request: ParsePythonDependenciesRequest,
    python_infer_subsystem: PythonInferSubsystem,
) -> PythonFilesDependencies:
    stripped_sources = await strip_source_roots(request.source)
    # We operate on PythonSourceField, which should be one file.
    assert len(stripped_sources.snapshot.files) == 1

    native_results = await parse_python_deps(
        NativeDependenciesRequest(stripped_sources.snapshot.digest)
    )

    path_to_deps = {}
    for path, native_result in native_results.path_to_deps.items():
        imports = dict(native_result.imports)
        assets = set()

        if python_infer_subsystem.string_imports or python_infer_subsystem.assets:
            for string, line in native_result.string_candidates.items():
                if (
                    python_infer_subsystem.string_imports
                    and string.count(".") >= python_infer_subsystem.string_imports_min_dots
                    and all(part.isidentifier() for part in string.split("."))
                ):
                    imports.setdefault(string, (line, True))
                if (
                    python_infer_subsystem.assets
                    and string.count("/") >= python_infer_subsystem.assets_min_slashes
                ):
                    assets.add(string)

        path_to_deps[path] = PythonFileDependencies(
            ParsedPythonImports(
                (key, ParsedPythonImportInfo(*value)) for key, value in imports.items()
            ),
            ParsedPythonAssetPaths(sorted(assets)),
        )
    return PythonFilesDependencies(FrozenDict(path_to_deps))


def rules():
    return [
        *collect_rules(),
    ]
