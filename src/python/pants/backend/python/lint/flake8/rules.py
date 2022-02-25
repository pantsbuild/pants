# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.flake8.subsystem import (
    Flake8,
    Flake8FieldSet,
    Flake8FirstPartyPlugins,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.lint import REPORT_DIR, LintResult, LintResults, LintTargetsRequest
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class Flake8Request(LintTargetsRequest):
    field_set_type = Flake8FieldSet
    name = Flake8.options_scope


@dataclass(frozen=True)
class Flake8Partition:
    field_sets: Tuple[Flake8FieldSet, ...]
    interpreter_constraints: InterpreterConstraints


def generate_argv(source_files: SourceFiles, flake8: Flake8) -> Tuple[str, ...]:
    args = []
    if flake8.config:
        args.append(f"--config={flake8.config}")
    args.append("--jobs={pants_concurrency}")
    args.extend(flake8.args)
    args.extend(source_files.files)
    return tuple(args)


@rule(level=LogLevel.DEBUG)
async def flake8_lint_partition(
    partition: Flake8Partition, flake8: Flake8, first_party_plugins: Flake8FirstPartyPlugins
) -> LintResult:
    flake8_pex_get = Get(
        VenvPex,
        PexRequest,
        flake8.to_pex_request(
            interpreter_constraints=partition.interpreter_constraints,
            extra_requirements=first_party_plugins.requirement_strings,
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
            (
                source_files.snapshot.digest,
                first_party_plugins.sources_digest,
                config_files.snapshot.digest,
                report_directory,
            )
        ),
    )

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            flake8_pex,
            argv=generate_argv(source_files, flake8),
            input_digest=input_digest,
            output_directories=(REPORT_DIR,),
            extra_env={"PEX_EXTRA_SYS_PATH": first_party_plugins.PREFIX},
            concurrency_available=len(partition.field_sets),
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
    request: Flake8Request,
    flake8: Flake8,
    python_setup: PythonSetup,
    first_party_plugins: Flake8FirstPartyPlugins,
) -> LintResults:
    if flake8.skip:
        return LintResults([], linter_name=request.name)

    # NB: Flake8 output depends upon which Python interpreter version it's run with
    # (http://flake8.pycqa.org/en/latest/user/invocation.html). We batch targets by their
    # constraints to ensure, for example, that all Python 2 targets run together and all Python 3
    # targets run together.
    results = defaultdict(set)
    for fs in request.field_sets:
        constraints = InterpreterConstraints.create_from_compatibility_fields(
            [fs.interpreter_constraints, *first_party_plugins.interpreter_constraints_fields],
            python_setup,
        )
        results[constraints].add(fs)

    partitioned_results = await MultiGet(
        Get(
            LintResult,
            Flake8Partition(tuple(sorted(field_sets, key=lambda fs: fs.address)), constraints),
        )
        for constraints, field_sets in sorted(results.items())
    )
    return LintResults(partitioned_results, linter_name=request.name)


def rules():
    return [*collect_rules(), UnionRule(LintTargetsRequest, Flake8Request), *pex.rules()]
