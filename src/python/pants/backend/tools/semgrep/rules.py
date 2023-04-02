# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import Partition, Partitions
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests, PathGlobs, Snapshot
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, Rule, collect_rules, rule
from pants.engine.target import DependenciesRequest, Targets
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize, softwrap

from .subsystem import Semgrep, SemgrepFieldSet
from .target_types import SemgrepRuleSourceField

logger = logging.getLogger(__name__)


class SemgrepRequest(LintTargetsRequest):
    field_set_type = SemgrepFieldSet
    tool_subsystem = Semgrep


@dataclass(frozen=True)
class PartitionMetadata:
    config_files: frozenset[SemgrepRuleSourceField]

    @property
    def description(self) -> str:
        return ", ".join(sorted(field.value for field in self.config_files))


@rule
async def partition(
    request: SemgrepRequest.PartitionRequest[SemgrepFieldSet], semgrep: Semgrep
) -> Partitions:
    if semgrep.skip:
        return Partitions()

    dependencies = await MultiGet(
        Get(Targets, DependenciesRequest(field_set.dependencies))
        for field_set in request.field_sets
    )

    # partition by the sets of configs that apply to each input
    by_config = defaultdict(list)
    for field_set, deps in zip(request.field_sets, dependencies):
        semgrep_configs = frozenset(
            d[SemgrepRuleSourceField] for d in deps if d.has_field(SemgrepRuleSourceField)
        )

        if semgrep_configs:
            by_config[semgrep_configs].append(field_set)

    return Partitions(
        Partition(tuple(field_sets), PartitionMetadata(configs))
        for configs, field_sets in by_config.items()
    )


@dataclass
class SemgrepIgnoreFiles:
    digest: Digest


@rule
async def find_semgrep_ignore_files() -> SemgrepIgnoreFiles:
    # if .semgrep gets support for nested ignore files, these should be involved in config
    # partitioning too
    ignore_name = ".semgrepignore"
    ignore_files = await Get(Snapshot, PathGlobs([f"**/{ignore_name}"]))
    non_root_ignores = sorted(name for name in ignore_files.files if name != ignore_name)
    if non_root_ignores:
        # https://github.com/returntocorp/semgrep/issues/5669
        logger.warning(
            softwrap(
                f"""
                Semgrep does not support {ignore_name} files anywhere other than its working
                directory, which is the build root when running under pants. These files will be
                ignored: {', '.join(non_root_ignores)}
                """
            )
        )

    return SemgrepIgnoreFiles(digest=ignore_files.digest)


# We have a hard-coded settings file to side-step
# https://github.com/returntocorp/semgrep/issues/7102, and also provide more cacheability.
_DEFAULT_SETTINGS = FileContent(
    path="__semgrep_settings.yaml",
    content=b"has_shown_metrics_notification: true",
)


@rule(desc="Lint with Semgrep", level=LogLevel.DEBUG)
async def lint(
    request: SemgrepRequest.Batch[SemgrepFieldSet, PartitionMetadata],
    semgrep: Semgrep,
    ignore_files: SemgrepIgnoreFiles,
    global_options: GlobalOptions,
) -> LintResult:
    config_files, semgrep_pex, input_files, settings = await MultiGet(
        Get(SourceFiles, SourceFilesRequest(request.partition_metadata.config_files)),
        Get(VenvPex, PexRequest, semgrep.to_pex_request()),
        Get(SourceFiles, SourceFilesRequest(field_set.source for field_set in request.elements)),
        Get(Digest, CreateDigest([_DEFAULT_SETTINGS])),
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                input_files.snapshot.digest,
                config_files.snapshot.digest,
                settings,
                ignore_files.digest,
            )
        ),
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
