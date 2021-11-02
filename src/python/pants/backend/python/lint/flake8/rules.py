# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.flake8.subsystem import Flake8, Flake8FieldSet
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.lint import REPORT_DIR, LintRequest, LintResult, LintResults
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class Flake8Request(LintRequest):
    field_set_type = Flake8FieldSet


@dataclass(frozen=True)
class Flake8Partition:
    field_sets: Tuple[Flake8FieldSet, ...]
    interpreter_constraints: InterpreterConstraints


def generate_argv(source_files: SourceFiles, flake8: Flake8) -> Tuple[str, ...]:
    args = []
    if flake8.config:
        args.append(f"--config={flake8.config}")
    args.extend(flake8.args)
    args.extend(source_files.files)
    return tuple(args)


@rule(level=LogLevel.DEBUG)
async def flake8_lint_partition(partition: Flake8Partition, flake8: Flake8) -> LintResult:
    flake8_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="flake8.pex",
            internal_only=True,
            requirements=flake8.pex_requirements(),
            interpreter_constraints=partition.interpreter_constraints,
            main=flake8.main,
        ),
    )
    config_files_get = Get(ConfigFiles, ConfigFilesRequest, flake8.config_request)
    source_files_get = Get(
        SourceFiles, SourceFilesRequest(field_set.source for field_set in partition.field_sets)
    )
    # Ensure that the empty report dir exists.
    report_directory_digest_get = Get(Digest, CreateDigest([Directory(REPORT_DIR)]))
    flake8_pex, config_files, report_directory, source_files = await MultiGet(
        flake8_pex_get, config_files_get, report_directory_digest_get, source_files_get
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (source_files.snapshot.digest, config_files.snapshot.digest, report_directory)
        ),
    )

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            flake8_pex,
            argv=generate_argv(source_files, flake8),
            input_digest=input_digest,
            output_directories=(REPORT_DIR,),
            description=f"Run Flake8 on {pluralize(len(partition.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    report = await Get(Digest, RemovePrefix(result.output_digest, REPORT_DIR))
    return LintResult.from_fallible_process_result(
        result,
        partition_description=str(sorted(str(c) for c in partition.interpreter_constraints)),
        report=report,
    )


@rule(desc="Lint with Flake8", level=LogLevel.DEBUG)
async def flake8_lint(
    request: Flake8Request, flake8: Flake8, python_setup: PythonSetup
) -> LintResults:
    if flake8.skip:
        return LintResults([], linter_name="Flake8")

    # NB: Flake8 output depends upon which Python interpreter version it's run with
    # (http://flake8.pycqa.org/en/latest/user/invocation.html). We batch targets by their
    # constraints to ensure, for example, that all Python 2 targets run together and all Python 3
    # targets run together.
    constraints_to_field_sets = InterpreterConstraints.group_field_sets_by_constraints(
        request.field_sets, python_setup
    )
    partitioned_results = await MultiGet(
        Get(LintResult, Flake8Partition(partition_field_sets, partition_compatibility))
        for partition_compatibility, partition_field_sets in constraints_to_field_sets.items()
    )
    return LintResults(partitioned_results, linter_name="Flake8")


def rules():
    return [*collect_rules(), UnionRule(LintRequest, Flake8Request), *pex.rules()]
