# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.lint.flake8.skip_field import SkipFlake8Field
from pants.backend.python.lint.flake8.subsystem import Flake8
from pants.backend.python.target_types import InterpreterConstraintsField, PythonSources
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import (
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
    VenvPex,
    VenvPexProcess,
)
from pants.core.goals.lint import LintReport, LintRequest, LintResult, LintResults, LintSubsystem
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, DigestSubset, GlobMatchErrorBehavior, MergeDigests, PathGlobs
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class Flake8FieldSet(FieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipFlake8Field).value


class Flake8Request(LintRequest):
    field_set_type = Flake8FieldSet


@dataclass(frozen=True)
class Flake8Partition:
    field_sets: Tuple[Flake8FieldSet, ...]
    interpreter_constraints: PexInterpreterConstraints


def generate_argv(
    source_files: SourceFiles, flake8: Flake8, *, report_file_name: Optional[str]
) -> Tuple[str, ...]:
    args = []
    if flake8.config:
        args.append(f"--config={flake8.config}")
    if report_file_name:
        args.append(f"--output-file={report_file_name}")
    args.extend(flake8.args)
    args.extend(source_files.files)
    return tuple(args)


@rule(level=LogLevel.DEBUG)
async def flake8_lint_partition(
    partition: Flake8Partition, flake8: Flake8, lint_subsystem: LintSubsystem
) -> LintResult:
    flake8_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="flake8.pex",
            internal_only=True,
            requirements=PexRequirements(flake8.all_requirements),
            interpreter_constraints=partition.interpreter_constraints,
            main=flake8.main,
        ),
    )
    config_files_get = Get(ConfigFiles, ConfigFilesRequest, flake8.config_request)
    source_files_get = Get(
        SourceFiles, SourceFilesRequest(field_set.sources for field_set in partition.field_sets)
    )
    flake8_pex, config_files, source_files = await MultiGet(
        flake8_pex_get, config_files_get, source_files_get
    )

    input_digest = await Get(
        Digest, MergeDigests((source_files.snapshot.digest, config_files.snapshot.digest))
    )

    report_file_name = "flake8_report.txt" if lint_subsystem.reports_dir else None

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            flake8_pex,
            argv=generate_argv(source_files, flake8, report_file_name=report_file_name),
            input_digest=input_digest,
            output_files=(report_file_name,) if report_file_name else None,
            description=f"Run Flake8 on {pluralize(len(partition.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )

    report = None
    if report_file_name:
        report_digest = await Get(
            Digest,
            DigestSubset(
                result.output_digest,
                PathGlobs(
                    [report_file_name],
                    glob_match_error_behavior=GlobMatchErrorBehavior.warn,
                    description_of_origin="Flake8 report file",
                ),
            ),
        )
        report = LintReport(report_file_name, report_digest)

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
    constraints_to_field_sets = PexInterpreterConstraints.group_field_sets_by_constraints(
        request.field_sets, python_setup
    )
    partitioned_results = await MultiGet(
        Get(LintResult, Flake8Partition(partition_field_sets, partition_compatibility))
        for partition_compatibility, partition_field_sets in constraints_to_field_sets.items()
    )
    return LintResults(partitioned_results, linter_name="Flake8")


def rules():
    return [*collect_rules(), UnionRule(LintRequest, Flake8Request), *pex.rules()]
