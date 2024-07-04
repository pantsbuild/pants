# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import Partition, Partitions
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import (
    CreateDigest,
    Digest,
    FileContent,
    MergeDigests,
    PathGlobs,
    Paths,
    Snapshot,
)
from pants.engine.process import FallibleProcessResult, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

from .subsystem import SemgrepFieldSet, SemgrepSubsystem

logger = logging.getLogger(__name__)


class SemgrepLintRequest(LintTargetsRequest):
    field_set_type = SemgrepFieldSet
    tool_subsystem = SemgrepSubsystem


@dataclass(frozen=True)
class PartitionMetadata:
    config_files: frozenset[PurePath]

    @property
    def description(self) -> str:
        return ", ".join(sorted(str(path) for path in self.config_files))


@dataclass
class AllSemgrepConfigs:
    configs_by_dir: dict[PurePath, set[PurePath]]

    def ancestor_configs(self, address: Address) -> Iterable[PurePath]:
        # TODO: introspect the semgrep rules and determine which (if any) apply to the files, e.g. a
        # Python file shouldn't depend on a .semgrep.yml that doesn't have any 'python' or 'generic'
        # rules, and similarly if there's path inclusions/exclusions.
        # TODO: this would be better as actual dependency inference (e.g. allows inspection, manual
        # addition/exclusion), but that can only infer 'full' dependencies and it is wrong (e.g. JVM
        # things break) for real code files to depend on this sort of non-code linter config; requires
        # dependency scopes or similar (https://github.com/pantsbuild/pants/issues/12794)
        spec = PurePath(address.spec_path)

        for ancestor in itertools.chain([spec], spec.parents):
            yield from self.configs_by_dir.get(ancestor, [])


def _group_by_semgrep_dir(config_dir: str, all_paths: Paths) -> AllSemgrepConfigs:
    configs_by_dir = defaultdict(set)
    for path_ in all_paths.files:
        path = PurePath(path_)
        # Rules like foo/bar/.semgrep/baz.yaml and foo/bar/.semgrep/baz/qux.yaml should apply to the
        # project at foo/bar
        config_directory = (
            PurePath(*path.parts[: path.parts.index(config_dir)])
            if config_dir in path.parts
            else path.parent
        )
        configs_by_dir[config_directory].add(path)

    return AllSemgrepConfigs(configs_by_dir)


@rule
async def find_all_semgrep_configs(semgrep: SemgrepSubsystem) -> AllSemgrepConfigs:
    rules_files_globs = (
        f"{semgrep.config_dir}/**/*.yml",
        f"{semgrep.config_dir}/**/*.yaml",
        ".semgrep.yml",
        ".semgrep.yaml",
    )

    all_paths = await Get(Paths, PathGlobs([f"**/{file_glob}" for file_glob in rules_files_globs]))
    return _group_by_semgrep_dir(semgrep.config_dir, all_paths)


@dataclass(frozen=True)
class RelevantSemgrepConfigsRequest:
    field_set: SemgrepFieldSet


class RelevantSemgrepConfigs(frozenset[PurePath]):
    pass


@rule
async def infer_relevant_semgrep_configs(
    request: RelevantSemgrepConfigsRequest, all_semgrep: AllSemgrepConfigs
) -> RelevantSemgrepConfigs:
    return RelevantSemgrepConfigs(all_semgrep.ancestor_configs(request.field_set.address))


@rule
async def partition(
    request: SemgrepLintRequest.PartitionRequest[SemgrepFieldSet],
    semgrep: SemgrepSubsystem,
) -> Partitions:
    if semgrep.skip:
        return Partitions()

    all_configs = await MultiGet(
        Get(RelevantSemgrepConfigs, RelevantSemgrepConfigsRequest(field_set))
        for field_set in request.field_sets
    )

    # partition by the sets of configs that apply to each input
    by_config = defaultdict(list)
    for field_set, configs in zip(request.field_sets, all_configs):
        if configs:
            by_config[configs].append(field_set)

    return Partitions(
        Partition(tuple(field_sets), PartitionMetadata(configs))
        for configs, field_sets in by_config.items()
    )


# We have a hard-coded settings file to side-step
# https://github.com/returntocorp/semgrep/issues/7102, and also provide more cacheability, NB. both
# keys are required.
_DEFAULT_SETTINGS = FileContent(
    path="__semgrep_settings.yaml",
    content=b"anonymous_user_id: 00000000-0000-0000-0000-000000000000\nhas_shown_metrics_notification: true",
)


@rule(desc="Lint with Semgrep", level=LogLevel.DEBUG)
async def lint(
    request: SemgrepLintRequest.Batch[SemgrepFieldSet, PartitionMetadata],
    semgrep: SemgrepSubsystem,
    global_options: GlobalOptions,
) -> LintResult:
    config_files, semgrep_pex, input_files, settings = await MultiGet(
        Get(Snapshot, PathGlobs(str(s) for s in request.partition_metadata.config_files)),
        Get(VenvPex, PexRequest, semgrep.to_pex_request()),
        Get(SourceFiles, SourceFilesRequest(field_set.source for field_set in request.elements)),
        Get(Digest, CreateDigest([_DEFAULT_SETTINGS])),
    )

    ignore_files = await Get(Snapshot, PathGlobs([semgrep.ignore_config_path]))

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                input_files.snapshot.digest,
                config_files.digest,
                settings,
                ignore_files.digest,
            )
        ),
    )

    cache_scope = ProcessCacheScope.PER_SESSION if semgrep.force else ProcessCacheScope.SUCCESSFUL

    # TODO: https://github.com/pantsbuild/pants/issues/18430 support running this with --autofix
    # under the fix goal... but not all rules have fixes, so we need to be running with
    # --error/checking exit codes, which FixResult doesn't currently support.
    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            semgrep_pex,
            argv=(
                "scan",
                *(f"--config={f}" for f in config_files.files),
                "--jobs={pants_concurrency}",
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
            cache_scope=cache_scope,
        ),
    )

    return LintResult.create(request, result, output_simplifier=global_options.output_simplifier())


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *SemgrepLintRequest.rules(), *pex.rules()]
