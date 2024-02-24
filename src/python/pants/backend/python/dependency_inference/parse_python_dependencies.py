# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.dependency_inference.subsystem import PythonInferSubsystem
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.base.deprecated import warn_or_error
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.collection import DeduplicatedCollection
from pants.engine.environment import EnvironmentName
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.native_dep_inference import NativeParsedPythonDependencies
from pants.engine.internals.native_engine import NativeDependenciesRequest
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.resources import read_resource
from pants.util.strutil import softwrap

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


@dataclass(frozen=True)
class ParsedPythonDependencies:
    imports: ParsedPythonImports
    assets: ParsedPythonAssetPaths


@dataclass(frozen=True)
class ParsePythonDependenciesRequest:
    source: PythonSourceField
    interpreter_constraints: InterpreterConstraints


@union(in_scope_types=[EnvironmentName])
class PythonDependencyVisitorRequest:
    pass


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

    digest = await Get(Digest, CreateDigest(contents))
    return digest


@rule
async def get_parser_script(union_membership: UnionMembership) -> ParserScript:
    dep_visitor_request_types = union_membership[PythonDependencyVisitorRequest]
    dep_visitors = await MultiGet(
        Get(PythonDependencyVisitor, PythonDependencyVisitorRequest, dvrt())
        for dvrt in dep_visitor_request_types
    )
    utils = await get_scripts_digest(
        _scripts_package,
        [
            "dependency_visitor_base.py",
            "main.py",
        ],
    )

    digest = await Get(Digest, MergeDigests([utils, *(dv.digest for dv in dep_visitors)]))
    env = {
        "VISITOR_CLASSNAMES": "|".join(dv.classname for dv in dep_visitors),
        "PYTHONPATH": ".",
    }
    for dv in dep_visitors:
        for k, v in dv.env.items():
            if k in env:
                existing_v = env[k]
                raise ValueError(
                    softwrap(
                        f"""
                        Environment variable {k} was set to value {existing_v} by a "
                        PythonDependencyVisitor implementation, cannot reset it to {v}."
                    """
                    )
                )
            env[k] = v
    return ParserScript(digest, FrozenDict(env))


@dataclass(frozen=True)
class GeneralPythonDependencyVisitorRequest(PythonDependencyVisitorRequest):
    # Union member for the general dep parser that applies to all .py files.
    pass


@rule
async def general_parser_script(
    python_infer_subsystem: PythonInferSubsystem,
    _: GeneralPythonDependencyVisitorRequest,
) -> PythonDependencyVisitor:
    script_digest = await get_scripts_digest(_scripts_package, ["general_dependency_visitor.py"])
    classname = f"{_scripts_package}.general_dependency_visitor.GeneralDependencyVisitor"
    return PythonDependencyVisitor(
        digest=script_digest,
        classname=classname,
        env=FrozenDict(
            {
                "STRING_IMPORTS": "y" if python_infer_subsystem.string_imports else "n",
                "STRING_IMPORTS_MIN_DOTS": str(python_infer_subsystem.string_imports_min_dots),
                "ASSETS": "y" if python_infer_subsystem.assets else "n",
                "ASSETS_MIN_SLASHES": str(python_infer_subsystem.assets_min_slashes),
            }
        ),
    )


@rule(level=LogLevel.DEBUG)
async def parse_python_dependencies(
    request: ParsePythonDependenciesRequest,
    parser_script: ParserScript,
    union_membership: UnionMembership,
    python_infer_subsystem: PythonInferSubsystem,
) -> ParsedPythonDependencies:
    stripped_sources = await Get(StrippedSourceFiles, SourceFilesRequest([request.source]))
    # We operate on PythonSourceField, which should be one file.
    assert len(stripped_sources.snapshot.files) == 1

    if not python_infer_subsystem.use_rust_parser:
        # NB: In 2.19, we remove the option altogether and remove the old code.
        warn_or_error(
            removal_version="2.19.0.dev0",
            entity="Setting [python-infer].use_rust_parser to false",
            hint=softwrap(
                f"""
                Read the help for [python-infer].use_rust_parser
                <{doc_url('reference-python-infer#use_rust_parser')}>, then stop setting the value
                in pants.toml.
                """
            ),
        )

    has_custom_dep_inferences = len(union_membership[PythonDependencyVisitorRequest]) > 1
    if python_infer_subsystem.use_rust_parser and not has_custom_dep_inferences:
        native_result = await Get(
            NativeParsedPythonDependencies,
            NativeDependenciesRequest(stripped_sources.snapshot.digest),
        )
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

        return ParsedPythonDependencies(
            ParsedPythonImports(
                (key, ParsedPythonImportInfo(*value)) for key, value in imports.items()
            ),
            ParsedPythonAssetPaths(sorted(assets)),
        )

    file = stripped_sources.snapshot.files[0]

    python_interpreter, input_digest = await MultiGet(
        Get(PythonExecutable, InterpreterConstraints, request.interpreter_constraints),
        Get(Digest, MergeDigests([parser_script.digest, stripped_sources.snapshot.digest])),
    )
    process_result = await Get(
        ProcessResult,
        Process(
            argv=[
                python_interpreter.path,
                "pants/backend/python/dependency_inference/scripts/main.py",
                file,
            ],
            input_digest=input_digest,
            append_only_caches=python_interpreter.append_only_caches,
            description=f"Determine Python dependencies for {request.source.address}",
            env=parser_script.env,
            level=LogLevel.DEBUG,
        ),
    )
    # See in script for where we explicitly encoded as utf8. Even though utf8 is the
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
    return [
        UnionRule(PythonDependencyVisitorRequest, GeneralPythonDependencyVisitorRequest),
        *collect_rules(),
    ]
