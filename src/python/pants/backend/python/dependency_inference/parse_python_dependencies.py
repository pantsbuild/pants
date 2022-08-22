# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from dataclasses import dataclass

from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.collection import DeduplicatedCollection
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.resources import read_resource


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class ParsedPythonDependencies:
    imports: ParsedPythonImports
    assets: ParsedPythonAssetPaths


@dataclass(frozen=True)
class ParsePythonDependenciesRequest:
    source: PythonSourceField
    interpreter_constraints: InterpreterConstraints
    string_imports: bool
    string_imports_min_dots: int
    assets: bool
    assets_min_slashes: int


@dataclass(frozen=True)
class ParserScript:
    digest: Digest


@rule
async def parser_script() -> ParserScript:
    script = read_resource(__name__, "scripts/dependency_parser_py")
    assert script is not None
    return ParserScript(
        await Get(Digest, CreateDigest([FileContent("__parse_python_dependencies.py", script)]))
    )


@rule
async def parse_python_dependencies(
    request: ParsePythonDependenciesRequest,
    parser_script: ParserScript,
) -> ParsedPythonDependencies:
    python_interpreter, stripped_sources = await MultiGet(
        Get(PythonExecutable, InterpreterConstraints, request.interpreter_constraints),
        Get(StrippedSourceFiles, SourceFilesRequest([request.source])),
    )

    # We operate on PythonSourceField, which should be one file.
    assert len(stripped_sources.snapshot.files) == 1
    file = stripped_sources.snapshot.files[0]

    input_digest = await Get(
        Digest, MergeDigests([parser_script.digest, stripped_sources.snapshot.digest])
    )
    process_result = await Get(
        ProcessResult,
        Process(
            argv=[
                python_interpreter.path,
                "./__parse_python_dependencies.py",
                file,
            ],
            input_digest=input_digest,
            description=f"Determine Python dependencies for {request.source.address}",
            env={
                "STRING_IMPORTS": "y" if request.string_imports else "n",
                "STRING_IMPORTS_MIN_DOTS": str(request.string_imports_min_dots),
                "ASSETS": "y" if request.assets else "n",
                "ASSETS_MIN_SLASHES": str(request.assets_min_slashes),
            },
            level=LogLevel.DEBUG,
        ),
    )
    # See above for where we explicitly encoded as utf8. Even though utf8 is the
    # default for decode(), we make that explicit here for emphasis.
    process_output = process_result.stdout.decode("utf8") or "{}"
    output = json.loads(process_output)

    return ParsedPythonDependencies(
        imports=ParsedPythonImports(
            (key, ParsedPythonImportInfo(**val)) for key, val in output.get("imports", {}).items()
        ),
        assets=ParsedPythonAssetPaths(output.get("assets", [])),
    )


def rules():
    return collect_rules()
