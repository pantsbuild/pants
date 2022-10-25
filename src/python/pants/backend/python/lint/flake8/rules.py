# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
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
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core.goals.lint import REPORT_DIR, LintResult, LintTargetsRequest, Partitions
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.partitions import Partition
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, PathGlobs, RemovePrefix
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class Flake8Request(LintTargetsRequest):
    field_set_type = Flake8FieldSet
    tool_subsystem = Flake8


def generate_argv(source_files: SourceFiles, flake8: Flake8) -> Tuple[str, ...]:
    args = []
    if flake8.config:
        args.append(f"--config={flake8.config}")
    args.append("--jobs={pants_concurrency}")
    args.extend(flake8.args)
    args.extend(source_files.files)
    return tuple(args)


@rule
async def partition_flake8(
    request: Flake8Request.PartitionRequest[Flake8FieldSet],
    flake8: Flake8,
    python_setup: PythonSetup,
    first_party_plugins: Flake8FirstPartyPlugins,
) -> Partitions[Flake8FieldSet, InterpreterConstraints]:
    if flake8.skip:
        return Partitions()

    results: dict[InterpreterConstraints, list[Flake8FieldSet]] = defaultdict(list)
    for fs in request.field_sets:
        constraints = InterpreterConstraints.create_from_compatibility_fields(
            [fs.interpreter_constraints, *first_party_plugins.interpreter_constraints_fields],
            python_setup,
        )
        results[constraints].append(fs)

    return Partitions(
        Partition(tuple(field_sets), interpreter_constraints)
        for interpreter_constraints, field_sets in results.items()
    )


@rule(desc="Lint with Flake8", level=LogLevel.DEBUG)
async def run_flake8(
    request: Flake8Request.Batch[Flake8FieldSet, InterpreterConstraints],
    flake8: Flake8,
    first_party_plugins: Flake8FirstPartyPlugins,
) -> LintResult:
    interpreter_constraints = request.partition_metadata
    flake8_pex_get = Get(
        VenvPex,
        PexRequest,
        flake8.to_pex_request(
            interpreter_constraints=interpreter_constraints,
            extra_requirements=first_party_plugins.requirement_strings,
        ),
    )
    config_files_get = Get(ConfigFiles, ConfigFilesRequest, flake8.config_request)
    source_files_get = Get(
        SourceFiles, SourceFilesRequest(field_set.source for field_set in request.elements)
    )
    extra_files_get = Get(
        Digest,
        PathGlobs(
            globs=flake8.extra_files,
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option [flake8].extra_files",
        ),
    )
    # Ensure that the empty report dir exists.
    report_directory_digest_get = Get(Digest, CreateDigest([Directory(REPORT_DIR)]))
    flake8_pex, config_files, report_directory, source_files, extra_files = await MultiGet(
        flake8_pex_get,
        config_files_get,
        report_directory_digest_get,
        source_files_get,
        extra_files_get,
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                source_files.snapshot.digest,
                first_party_plugins.sources_digest,
                config_files.snapshot.digest,
                extra_files,
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
            concurrency_available=len(request.elements),
            description=f"Run Flake8 on {pluralize(len(request.elements), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    report = await Get(Digest, RemovePrefix(result.output_digest, REPORT_DIR))
    return LintResult.create(request, result, report=report)


def rules():
    return [
        *collect_rules(),
        *Flake8Request.rules(),
        *pex.rules(),
    ]
