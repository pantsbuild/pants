# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import Partition, Partitions
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests, PathGlobs, Snapshot
from pants.engine.process import FallibleProcessResult, ProcessCacheScope
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
    ignore_files: Snapshot

    @property
    def description(self) -> str:
        return ", ".join(sorted(field.value for field in self.config_files))


_IGNORE_FILE_NAME = ".semgrepignore"


def warn_about_ignore_files_if_required(ignore_files: Snapshot, semgrep: Semgrep) -> None:
    non_root_files = sorted(name for name in ignore_files.files if name != _IGNORE_FILE_NAME)
    if non_root_files and not semgrep.acknowledge_nested_semgrepignore_files_are_not_used:
        # https://github.com/returntocorp/semgrep/issues/5669
        logger.warning(
            softwrap(
                f"""
                Semgrep does not obey {_IGNORE_FILE_NAME} outside the working directory, which is
                the build root when run by pants. These files may not have the desired effect:
                {', '.join(non_root_files)}

                Set `acknowledge_nested_semgrepignore_files_are_not_used = true` in the `[semgrep]`
                section of pants.toml to silence this warning.
                """
            )
        )


@dataclass
class SemgrepIgnoreFiles:
    snapshot: Snapshot


@rule
async def all_semgrep_ignore_files() -> SemgrepIgnoreFiles:
    snapshot = await Get(Snapshot, PathGlobs([f"**/{_IGNORE_FILE_NAME}"]))
    return SemgrepIgnoreFiles(snapshot)


@rule
async def partition(
    request: SemgrepRequest.PartitionRequest[SemgrepFieldSet],
    semgrep: Semgrep,
    ignore_files: SemgrepIgnoreFiles,
) -> Partitions:
    if semgrep.skip:
        return Partitions()

    warn_about_ignore_files_if_required(ignore_files.snapshot, semgrep)

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
        Partition(tuple(field_sets), PartitionMetadata(configs, ignore_files.snapshot))
        for configs, field_sets in by_config.items()
    )


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
                request.partition_metadata.ignore_files.digest,
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
                # we don't pass the target files directly because that overrides .semgrepignore
                # (https://github.com/returntocorp/semgrep/issues/4978), so instead we just tell its
                # traversal to include all the source files in this partition. Unfortunately this
                # include is implicitly unrooted (i.e. as if it was **/path/to/file), and so may
                # pick up other files if the names match. The highest risk of this is within the
                # semgrep PEX.
                *(f"--include={f}" for f in input_files.files),
                f"--exclude={semgrep_pex.pex_filename}",
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
            cache_scope=ProcessCacheScope.PER_SESSION
            if semgrep.force
            else ProcessCacheScope.SUCCESSFUL,
        ),
    )

    return LintResult.create(request, result, strip_formatting=not global_options.colors)


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *SemgrepRequest.rules(), *pex.rules()]
