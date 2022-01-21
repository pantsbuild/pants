# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import pkgutil
from dataclasses import dataclass

from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


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


@dataclass(frozen=True)
class ParsePythonImportsRequest:
    source: PythonSourceField
    interpreter_constraints: InterpreterConstraints
    string_imports: bool
    string_imports_min_dots: int


@rule
async def parse_python_imports(request: ParsePythonImportsRequest) -> ParsedPythonImports:
    script = pkgutil.get_data(__name__, "scripts/import_parser.py")
    assert script is not None
    python_interpreter, script_digest, stripped_sources = await MultiGet(
        Get(PythonExecutable, InterpreterConstraints, request.interpreter_constraints),
        Get(Digest, CreateDigest([FileContent("__parse_python_imports.py", script)])),
        Get(StrippedSourceFiles, SourceFilesRequest([request.source])),
    )

    # We operate on PythonSourceField, which should be one file.
    assert len(stripped_sources.snapshot.files) == 1
    file = stripped_sources.snapshot.files[0]

    input_digest = await Get(
        Digest, MergeDigests([script_digest, stripped_sources.snapshot.digest])
    )
    process_result = await Get(
        ProcessResult,
        Process(
            argv=[
                python_interpreter.path,
                "./__parse_python_imports.py",
                file,
            ],
            input_digest=input_digest,
            description=f"Determine Python imports for {request.source.address}",
            env={
                "STRING_IMPORTS": "y" if request.string_imports else "n",
                "MIN_DOTS": str(request.string_imports_min_dots),
            },
            level=LogLevel.DEBUG,
        ),
    )
    # See above for where we explicitly encoded as utf8. Even though utf8 is the
    # default for decode(), we make that explicit here for emphasis.
    process_output = process_result.stdout.decode("utf8") or "{}"
    return ParsedPythonImports(
        (imp, ParsedPythonImportInfo(**info)) for imp, info in json.loads(process_output).items()
    )


def rules():
    return collect_rules()
