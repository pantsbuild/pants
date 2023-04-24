# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import logging
import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.dependency_inference.subsystem import PythonInferSubsystem
from pants.backend.python.dependency_inference.idk import ParsedPythonAssetPaths, ParsedPythonDependencies, ParsedPythonImportInfo, ParsedPythonImports
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.environment import EnvironmentName
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.resources import read_resource
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)



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


@rule
async def parse_python_dependencies(
    request: ParsePythonDependenciesRequest,
    parser_script: ParserScript,
) -> ParsedPythonDependencies:
    python_interpreter, stripped_sources = await MultiGet(
        Get(PythonExecutable, InterpreterConstraints, request.interpreter_constraints),
        Get(StrippedSourceFiles, SourceFilesRequest([request.source])),
    )

    native_result = await Get(ParsedPythonDependencies, Digest, stripped_sources.snapshot.digest)
    logger.warn(native_result)

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
