# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.target_types import PythonInterpreterCompatibility, PythonSources
from pants.backend.python.typecheck.mypy.subsystem import MyPy
from pants.backend.python.util_rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexProcess,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.backend.python.util_rules.python_sources import rules as python_sources_rules
from pants.core.goals.typecheck import TypecheckRequest, TypecheckResult, TypecheckResults
from pants.core.util_rules import pants_bin
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    CreateDigest,
    Digest,
    FileContent,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, TransitiveTargets
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MyPyFieldSet(FieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources


class MyPyRequest(TypecheckRequest):
    field_set_type = MyPyFieldSet


def generate_args(mypy: MyPy, *, file_list_path: str) -> Tuple[str, ...]:
    args = []
    if mypy.config:
        args.append(f"--config-file={mypy.config}")
    args.extend(mypy.args)
    args.append(f"@{file_list_path}")
    return tuple(args)


# TODO(#10131): Improve performance, e.g. by leveraging the MyPy cache.
# TODO(#10131): Support plugins and type stubs.
# TODO(#10131): Support third-party requirements.
@rule(desc="Typecheck using MyPy", level=LogLevel.DEBUG)
async def mypy_typecheck(
    request: MyPyRequest, mypy: MyPy, python_setup: PythonSetup
) -> TypecheckResults:
    if mypy.skip:
        return TypecheckResults([], typechecker_name="MyPy")

    transitive_targets = await Get(
        TransitiveTargets, Addresses(fs.address for fs in request.field_sets)
    )

    # Interpreter constraints are tricky with MyPy:
    #  * MyPy requires running with Python 3.5+. If run with Python 3.5 - 3.7, MyPy can understand
    #     Python 2.7 and 3.4-3.7 thanks to the typed-ast library, but it can't understand 3.8+ If
    #     run with Python 3.8, it can understand 2.7 and 3.4-3.8. So, we need to check if the user
    #     has code that requires Python 3.8+, and if so, use a tighter requirement. We only do this
    #     if <3.8 can't be used, as we don't want a loose requirement like `>=3.6` to result in
    #     requiring Python 3.8, which would error if 3.8 is not installed on the machine.
    #  * We must resolve third-party dependencies. This should use whatever the actual code's
    #     constraints are, as the constraints for the tool can be different than for the
    #     requirements.
    #  * The runner Pex should use the same constraints as the tool Pex.
    all_interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (
            tgt[PythonInterpreterCompatibility]
            for tgt in transitive_targets.closure
            if tgt.has_field(PythonInterpreterCompatibility)
        ),
        python_setup,
    )
    tool_interpreter_constraints = PexInterpreterConstraints(
        mypy.interpreter_constraints
        if not all_interpreter_constraints.requires_python38_or_newer()
        else ("CPython>=3.8",)
    )

    prepared_sources_request = Get(
        PythonSourceFiles,
        PythonSourceFilesRequest(transitive_targets.closure),
    )
    pex_request = Get(
        Pex,
        PexRequest(
            output_filename="mypy.pex",
            internal_only=True,
            requirements=PexRequirements(mypy.all_requirements),
            interpreter_constraints=tool_interpreter_constraints,
            entry_point=mypy.entry_point,
        ),
    )
    config_digest_request = Get(
        Digest,
        PathGlobs(
            globs=[mypy.config] if mypy.config else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--mypy-config`",
        ),
    )
    prepared_sources, pex, config_digest = await MultiGet(
        prepared_sources_request, pex_request, config_digest_request
    )

    srcs_snapshot = prepared_sources.source_files.snapshot
    file_list_path = "__files.txt"
    python_files = "\n".join(f for f in srcs_snapshot.files if f.endswith(".py"))
    file_list_digest = await Get(
        Digest,
        CreateDigest([FileContent(file_list_path, python_files.encode())]),
    )

    merged_input_files = await Get(
        Digest,
        MergeDigests([file_list_digest, srcs_snapshot.digest, pex.digest, config_digest]),
    )

    result = await Get(
        FallibleProcessResult,
        PexProcess(
            pex,
            argv=generate_args(mypy, file_list_path=file_list_path),
            input_digest=merged_input_files,
            extra_env={"PEX_EXTRA_SYS_PATH": ":".join(prepared_sources.source_roots)},
            description=f"Run MyPy on {pluralize(len(srcs_snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return TypecheckResults(
        [TypecheckResult.from_fallible_process_result(result)], typechecker_name="MyPy"
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(TypecheckRequest, MyPyRequest),
        *pants_bin.rules(),
        *pex_rules(),
        *python_sources_rules(),
    ]
