# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.lint import LintFilesRequest, LintResult
from pants.core.util_rules.partitions import PartitionerType, Partitions
from pants.engine.fs import (
    CreateDigest,
    Digest,
    FileContent,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.internals.native_engine import FilespecMatcher, Snapshot
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

from .subsystem import Semgrep


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
    globs = [f"**/{glob}" for glob in semgrep.config_globs]
    config_files_snapshot = await Get(
        Snapshot,
        PathGlobs(
            globs=globs,
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--semgrep-config-globs`",
        ),
    )
    return SemgrepConfigFiles(snapshot=config_files_snapshot)


@rule
async def partition(request: SemgrepRequest.PartitionRequest, semgrep: Semgrep) -> Partitions:
    if semgrep.skip:
        return Partitions()

    matching_files = FilespecMatcher(
        includes=semgrep.file_glob_include, excludes=semgrep.file_glob_exclude
    ).matches(request.files)

    # TODO: partition by config
    return Partitions.single_partition(matching_files)


# We have a hard-coded settings file to side-step
# https://github.com/returntocorp/semgrep/issues/7102, and also provide more cacheability.
_DEFAULT_SETTINGS = FileContent(
    path="__semgrep_settings.yaml",
    content=b"has_shown_metrics_notification: true",
)


@rule(desc="Lint with Semgrep", level=LogLevel.DEBUG)
async def lint(
    request: SemgrepRequest.Batch[str, Any],
    semgrep: Semgrep,
    global_options: GlobalOptions,
) -> LintResult:
    config_files, semgrep_pex, input_files, settings = await MultiGet(
        Get(SemgrepConfigFiles, SemgrepConfigFilesRequest()),
        Get(VenvPex, PexRequest, semgrep.to_pex_request()),
        Get(Snapshot, PathGlobs(globs=request.elements)),
        Get(Digest, CreateDigest([_DEFAULT_SETTINGS])),
    )

    input_digest = await Get(
        Digest, MergeDigests((input_files.digest, config_files.snapshot.digest, settings))
    )

    # TODO: https://github.com/pantsbuild/pants/issues/18430 support running this with --autofix
    # under the fix goal... but not all rules have fixes, so we need to be running with
    # --error/checking exit codes, which FixResult doesn't currently support.
    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            semgrep_pex,
            argv=(
                "scan",
                *(f"--config={f}" for f in config_files.snapshot.files),
                "-j",
                "{pants_concurrency}",
                "--error",
                *semgrep.args,
                *input_files.files,
            ),
            extra_env={
                "SEMGREP_FORCE_COLOR": "true",
                # disable various global state/network requests
                "SEMGREP_SETTINGS_FILE": _DEFAULT_SETTINGS.path,
                "SEMGREP_ENABLE_VERSION_CHECK": "0",
                "SEMGREP_SEND_METRICS": "off",
            },
            input_digest=input_digest,
            concurrency_available=len(input_files.files),
            description=f"Run Semgrep on {pluralize(len(input_files.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )

    return LintResult.create(request, result, strip_formatting=not global_options.colors)


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *SemgrepRequest.rules()]
