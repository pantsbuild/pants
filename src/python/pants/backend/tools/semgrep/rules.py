# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from pants.engine.process import FallibleProcessResult
from pants.backend.python.util_rules.pex import VenvPex, PexRequest, VenvPexProcess
from pants.core.util_rules.partitions import Partitions
from pants.core.goals.lint import LintFilesRequest, LintResult
from .subsystem import Semgrep
from pants.option.global_options import GlobalOptions
from pants.core.goals.fix import FixFilesRequest, FixResult
from pants.engine.rules import Rule
from pants.engine.unions import UnionRule
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.internals.native_engine import FilespecMatcher, Snapshot
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs
from pants.util.strutil import pluralize, softwrap


class SemgrepRequest(LintFilesRequest):
    tool_subsystem = Semgrep

    partitioner_type = PartitionerType.CUSTOM


@dataclass(frozen=True)
class SemgrepConfigFilesRequest:
    pass


@dataclass(frozen=True)
class SemgrepConfigFiles:
    snapshot: Snapshot


@rule
async def gather_config_files(
    request: SemgrepConfigFilesRequest, semgrep: Semgrep
) -> SemgrepConfigFiles:
    config_files_snapshot = await Get(Snapshot, PathGlobs(globs=[f"**/{name}" for name in semgrep.config_names]))
    return SemgrepConfigFiles(snapshot=config_files_snapshot)


@rule
async def partition(request: SemgrepRequest.PartitionRequest, semgrep: Semgrep) -> Partitions:
    if semgrep.skip:
        return Partitions()

    matching_files = FilespecMatcher(
        includes=semgrep.file_glob_include, excludes=semgrep.file_glob_exclude
    ).matches(request.files)

    return Partitions.single_partition(matching_files)


@rule(desc="Lint with Semgrep", level=LogLevel.DEBUG)
async def lint(
    request: SemgrepRequest.Batch[str, Any],
    semgrep: Semgrep,
    global_options: GlobalOptions,
) -> LintResult:
    config_files, semgrep_pex, input_files = await MultiGet(
        Get(SemgrepConfigFiles, SemgrepConfigFilesRequest()),
        Get(VenvPex, PexRequest, semgrep.to_pex_request()),
        Get(Snapshot, PathGlobs(globs=request.elements)),
    )

    input_digest = await Get(
        Digest, MergeDigests((input_files.digest, config_files.snapshot.digest))
    )

    # TODO: support running this under the fix goal if with --autofix if there's rules that have
    # fixes... but not all rules have fixes, so we need to be running with --error/checking exit
    # codes, which FixResult doesn't currently support.

    # TODO: concurrent runs occasionally hit "Bad settings format; ... will be overriden" errors
    # (https://github.com/returntocorp/semgrep/issues/7102).
    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            semgrep_pex,
            argv=(
                "scan",
                *(f"--config={f}" for f in config_files.snapshot.files),
                "-j",
                "{pants_concurrency}",
                "--force-color",
                "--disable-version-check",
                "--error",
                *semgrep.args,
                *input_files.files,
            ),
            input_digest=input_digest,
            concurrency_available=len(input_files.files),
            description=f"Run Semgrep on {pluralize(len(input_files.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )

    return LintResult.create(request, result, strip_formatting=not global_options.colors)


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *SemgrepRequest.rules()]
