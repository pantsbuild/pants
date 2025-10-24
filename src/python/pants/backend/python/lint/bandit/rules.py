# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.lint.bandit.subsystem import Bandit, BanditFieldSet
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import VenvPexProcess, create_venv_pex
from pants.core.goals.lint import REPORT_DIR, LintResult, LintTargetsRequest, Partitions
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.partitions import Partition
from pants.core.util_rules.source_files import (
    SourceFiles,
    SourceFilesRequest,
    determine_source_files,
)
from pants.engine.fs import CreateDigest, Directory, MergeDigests, RemovePrefix
from pants.engine.intrinsics import create_digest, execute_process, merge_digests, remove_prefix
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class BanditRequest(LintTargetsRequest):
    field_set_type = BanditFieldSet
    tool_subsystem = Bandit # type: ignore[assignment]


def generate_argv(source_files: SourceFiles, bandit: Bandit) -> tuple[str, ...]:
    args: list[str] = []
    if bandit.config is not None:
        args.append(f"--config={bandit.config}")
    args.extend(bandit.args)
    args.extend(source_files.files)
    return tuple(args)


@rule
async def partition_bandit(
    request: BanditRequest.PartitionRequest[BanditFieldSet],
    bandit: Bandit,
    python_setup: PythonSetup,
) -> Partitions[BanditFieldSet, InterpreterConstraints]:
    if bandit.skip:
        return Partitions()

    # NB: Bandit output depends upon which Python interpreter version it's run with
    # ( https://github.com/PyCQA/bandit#under-which-version-of-python-should-i-install-bandit).
    # We batch targets by their constraints to ensure, for example, that all Python 2 targets run
    # together and all Python 3 targets run together.
    constraints_to_field_sets = InterpreterConstraints.group_field_sets_by_constraints(
        request.field_sets, python_setup
    )

    return Partitions(
        Partition(field_sets, constraints)
        for constraints, field_sets in constraints_to_field_sets.items()
    )


@rule(desc="Lint with Bandit", level=LogLevel.DEBUG)
async def bandit_lint(
    request: BanditRequest.Batch[BanditFieldSet, InterpreterConstraints], bandit: Bandit
) -> LintResult:
    assert request.partition_metadata is not None

    interpreter_constraints = request.partition_metadata
    bandit_pex_get = create_venv_pex(
        **implicitly(bandit.to_pex_request(interpreter_constraints=interpreter_constraints))
    )
    config_files_get = find_config_file(bandit.config_request)
    source_files_get = determine_source_files(
        SourceFilesRequest(field_set.source for field_set in request.elements)
    )
    # Ensure that the empty report dir exists.
    report_directory_digest_get = create_digest(CreateDigest([Directory(REPORT_DIR)]))

    bandit_pex, config_files, report_directory, source_files = await concurrently(
        bandit_pex_get, config_files_get, report_directory_digest_get, source_files_get
    )

    input_digest = await merge_digests(
        MergeDigests((source_files.snapshot.digest, config_files.snapshot.digest, report_directory))
    )

    result = await execute_process(
        **implicitly(
            VenvPexProcess(
                bandit_pex,
                argv=generate_argv(source_files, bandit),
                input_digest=input_digest,
                description=f"Run Bandit on {pluralize(len(request.elements), 'file')}.",
                output_directories=(REPORT_DIR,),
                level=LogLevel.DEBUG,
            )
        )
    )
    report = await remove_prefix(RemovePrefix(result.output_digest, REPORT_DIR))
    return LintResult.create(request, result, report=report)


def rules():
    return (
        *collect_rules(),
        *BanditRequest.rules(),
        *pex.rules(),
    )
