# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript.subsystems.nodejs import NpxProcess
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.typecheck.pyright.subsystem import Pyright
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPex
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.target import CoarsenedTargets, CoarsenedTargetsRequest, FieldSet
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PyrightFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    sources: PythonSourceField


class PyrightRequest(CheckRequest):
    field_set_type = PyrightFieldSet
    tool_name = Pyright.options_scope


@rule(desc="Typecheck using Pyright", level=LogLevel.DEBUG)
async def pyright_typecheck(
    request: PyrightRequest,
    pyright: Pyright,
    pex_env: PexEnvironment,
) -> CheckResults:
    if pyright.skip:
        return CheckResults([], checker_name=request.tool_name)

    coarsened_targets = await Get(
        CoarsenedTargets,
        CoarsenedTargetsRequest(field_set.address for field_set in request.field_sets),
    )

    coarsened_sources = await Get(
        PythonSourceFiles, PythonSourceFilesRequest(coarsened_targets.closure())
    )

    source_files = await Get(
        SourceFiles, SourceFilesRequest([field_set.sources for field_set in request.field_sets])
    )

    # See `requirements_venv_pex` for how this will get wrapped in a `VenvPex`.
    requirements_pex = await Get(
        Pex,
        RequirementsPexRequest(
            (fs.address for fs in request.field_sets),
            # TODO: Setup the correct interpreter constraints after partitioning
            # hardcoded_interpreter_constraints=partition.interpreter_constraints,
        ),
    )

    requirements_venv_pex = await Get(
        VenvPex,
        PexRequest(
            output_filename="requirements_venv.pex",
            internal_only=True,
            pex_path=[requirements_pex],
            # TODO: Setup the correct interpreter constraints after partitioning
            interpreter_constraints=InterpreterConstraints(["==3.9.15"]),
        ),
    )

    # venv workaround as per: https://github.com/microsoft/pyright/issues/4051
    dummy_config_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    "pyrightconfig.json",
                    f'{{ "venv": "{requirements_venv_pex.venv_rel_dir}" }}'.encode(),
                )
            ]
        ),
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                coarsened_sources.source_files.snapshot.digest,
                requirements_venv_pex.digest,
                dummy_config_digest,
            ]
        ),
    )

    complete_pex_env = pex_env.in_workspace()
    process = await Get(
        Process,
        NpxProcess(
            npm_package=pyright.default_version,
            args=(
                f"--venv-path={complete_pex_env.pex_root}",  # Used with `venv` in config
                *pyright.args,  # User-added arguments
                *source_files.snapshot.files,
            ),
            input_digest=input_digest,
            description=f"Run Pyright on {pluralize(len(source_files.snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    result = await Get(FallibleProcessResult, Process, process)
    check_result = CheckResult.from_fallible_process_result(
        result,
    )

    return CheckResults(
        [check_result],
        checker_name=request.tool_name,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *pex_from_targets.rules(),
        UnionRule(CheckRequest, PyrightRequest),
    )
