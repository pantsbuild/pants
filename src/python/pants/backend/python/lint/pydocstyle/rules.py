# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Tuple

from pants.backend.python.lint.pydocstyle.subsystem import Pydocstyle, PydocstyleFieldSet
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.lint import LintResult, LintTargetsRequest, Partitions
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.partitions import Partition
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class PydocstyleRequest(LintTargetsRequest):
    field_set_type = PydocstyleFieldSet
    tool_subsystem = Pydocstyle


def generate_argv(source_files: SourceFiles, pydocstyle: Pydocstyle) -> Tuple[str, ...]:
    args = []
    if pydocstyle.config is not None:
        args.append(f"--config={pydocstyle.config}")
    args.extend(pydocstyle.args)
    args.extend(source_files.files)
    return tuple(args)


@rule
async def partition_pydocstyle(
    request: PydocstyleRequest.PartitionRequest[PydocstyleFieldSet],
    pydocstyle: Pydocstyle,
    python_setup: PythonSetup,
) -> Partitions[PydocstyleFieldSet, InterpreterConstraints]:
    if pydocstyle.skip:
        return Partitions()

    constraints_to_field_sets = InterpreterConstraints.group_field_sets_by_constraints(
        request.field_sets, python_setup
    )

    return Partitions(
        Partition(field_sets, constraints)
        for constraints, field_sets in constraints_to_field_sets.items()
    )


@rule(desc="Lint with Pydocstyle", level=LogLevel.DEBUG)
async def pydocstyle_lint(
    request: PydocstyleRequest.Batch[PydocstyleFieldSet, InterpreterConstraints],
    pydocstyle: Pydocstyle,
) -> LintResult:
    assert request.partition_metadata is not None

    interpreter_constraints = request.partition_metadata
    pydocstyle_pex_get = Get(
        VenvPex,
        PexRequest,
        pydocstyle.to_pex_request(interpreter_constraints=interpreter_constraints),
    )

    config_files_get = Get(ConfigFiles, ConfigFilesRequest, pydocstyle.config_request)
    source_files_get = Get(
        SourceFiles, SourceFilesRequest(field_set.source for field_set in request.elements)
    )

    pydocstyle_pex, config_files, source_files = await MultiGet(
        pydocstyle_pex_get, config_files_get, source_files_get
    )

    input_digest = await Get(
        Digest,
        MergeDigests((source_files.snapshot.digest, config_files.snapshot.digest)),
    )

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            pydocstyle_pex,
            argv=generate_argv(source_files, pydocstyle),
            input_digest=input_digest,
            description=f"Run Pydocstyle on {pluralize(len(request.elements), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return LintResult.create(request, result)


def rules():
    return [*collect_rules(), *PydocstyleRequest.rules(), *pex.rules()]
