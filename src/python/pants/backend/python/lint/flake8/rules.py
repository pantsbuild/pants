# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.lint.flake8.subsystem import Flake8
from pants.backend.python.rules import download_pex_bin, pex
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.backend.python.target_types import PythonInterpreterCompatibility, PythonSources
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules import determine_source_files, strip_source_roots
from pants.core.util_rules.determine_source_files import (
    AllSourceFilesRequest,
    SourceFiles,
    SpecifiedSourceFilesRequest,
)
from pants.engine.fs import Digest, MergeDigests, PathGlobs, Snapshot
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import FieldSetWithOrigin
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class Flake8FieldSet(FieldSetWithOrigin):
    required_fields = (PythonSources,)

    sources: PythonSources
    compatibility: PythonInterpreterCompatibility


class Flake8Request(LintRequest):
    field_set_type = Flake8FieldSet


@dataclass(frozen=True)
class Flake8Partition:
    field_sets: Tuple[Flake8FieldSet, ...]
    interpreter_constraints: PexInterpreterConstraints


def generate_args(*, specified_source_files: SourceFiles, flake8: Flake8) -> Tuple[str, ...]:
    args = []
    if flake8.options.config is not None:
        args.append(f"--config={flake8.options.config}")
    args.extend(flake8.options.args)
    args.extend(specified_source_files.files)
    return tuple(args)


@rule
async def flake8_lint_partition(
    partition: Flake8Partition,
    flake8: Flake8,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResult:
    requirements_pex_request = Get[Pex](
        PexRequest(
            output_filename="flake8.pex",
            requirements=PexRequirements(flake8.get_requirement_specs()),
            interpreter_constraints=(
                partition.interpreter_constraints
                or PexInterpreterConstraints(flake8.default_interpreter_constraints)
            ),
            entry_point=flake8.get_entry_point(),
        )
    )

    config_path: Optional[str] = flake8.options.config
    config_snapshot_request = Get[Snapshot](
        PathGlobs(
            globs=[config_path] if config_path else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--flake8-config`",
        )
    )

    all_source_files_request = Get[SourceFiles](
        AllSourceFilesRequest(field_set.sources for field_set in partition.field_sets)
    )
    specified_source_files_request = Get[SourceFiles](
        SpecifiedSourceFilesRequest(
            (field_set.sources, field_set.origin) for field_set in partition.field_sets
        )
    )

    requirements_pex, config_snapshot, all_source_files, specified_source_files = await MultiGet(
        requirements_pex_request,
        config_snapshot_request,
        all_source_files_request,
        specified_source_files_request,
    )

    input_digest = await Get[Digest](
        MergeDigests(
            (all_source_files.snapshot.digest, requirements_pex.digest, config_snapshot.digest)
        )
    )

    address_references = ", ".join(
        sorted(field_set.address.reference() for field_set in partition.field_sets)
    )

    process = requirements_pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./flake8.pex",
        pex_args=generate_args(specified_source_files=specified_source_files, flake8=flake8),
        input_digest=input_digest,
        description=(
            f"Run Flake8 on {pluralize(len(partition.field_sets), 'target')}: {address_references}."
        ),
    )
    result = await Get[FallibleProcessResult](Process, process)
    return LintResult.from_fallible_process_result(result, linter_name="Flake8")


@rule(desc="Lint using Flake8")
async def flake8_lint(
    request: Flake8Request, flake8: Flake8, python_setup: PythonSetup
) -> LintResults:
    if flake8.options.skip:
        return LintResults()

    # NB: Flake8 output depends upon which Python interpreter version it's run with
    # (http://flake8.pycqa.org/en/latest/user/invocation.html). We batch targets by their
    # constraints to ensure, for example, that all Python 2 targets run together and all Python 3
    # targets run together.
    constraints_to_field_sets = PexInterpreterConstraints.group_field_sets_by_constraints(
        request.field_sets, python_setup
    )
    partitioned_results = await MultiGet(
        Get[LintResult](Flake8Partition(partition_field_sets, partition_compatibility))
        for partition_compatibility, partition_field_sets in constraints_to_field_sets.items()
    )
    return LintResults(partitioned_results)


def rules():
    return [
        flake8_lint,
        flake8_lint_partition,
        SubsystemRule(Flake8),
        UnionRule(LintRequest, Flake8Request),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
