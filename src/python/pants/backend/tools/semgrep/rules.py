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
from pants.backend.python.util_rules.pex import VenvPexProcess, create_venv_pex
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import Partition, Partitions
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, FileContent, MergeDigests, PathGlobs, Paths, Snapshot
from pants.engine.intrinsics import (
    create_digest_to_digest,
    digest_to_snapshot,
    merge_digests_request_to_digest,
    path_globs_to_paths,
    process_request_to_process_result,
)
from pants.engine.process import ProcessCacheScope
from pants.engine.rules import Rule, collect_rules, concurrently, implicitly, rule
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

from .subsystem import SemgrepFieldSet, SemgrepSubsystem

logger = logging.getLogger(__name__)


_SEMGREPIGNORE_FILE_NAME = ".semgrepignore"
_DEFAULT_SEMGREP_CONFIG_DIR = ".semgrep"


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


def _group_by_semgrep_dir(
    all_config_files: Paths, all_config_dir_files: Paths, config_name: str
) -> AllSemgrepConfigs:
    configs_by_dir: dict[PurePath, set[PurePath]] = {}
    for config_path in all_config_files.files:
        # Rules like foo/semgrep.yaml should apply to the project at foo/
        path = PurePath(config_path)
        configs_by_dir.setdefault(path.parent, set()).add(path)

    for config_path in all_config_dir_files.files:
        # Rules like foo/bar/.semgrep/baz.yaml and foo/bar/.semgrep/baz/qux.yaml should apply to the
        # project at foo/bar/
        path = PurePath(config_path)
        config_directory = next(
            parent.parent for parent in path.parents if parent.name == config_name
        )
        configs_by_dir.setdefault(config_directory, set()).add(path)

    return AllSemgrepConfigs(configs_by_dir)


@rule
async def find_all_semgrep_configs(semgrep: SemgrepSubsystem) -> AllSemgrepConfigs:
    config_file_globs: tuple[str, ...] = ()
    config_dir_globs: tuple[str, ...] = ()

    if semgrep.config_name is None:
        config_file_globs = ("**/.semgrep.yml", "**/.semgrep.yaml")
        config_dir_globs = (
            f"**/{_DEFAULT_SEMGREP_CONFIG_DIR}/**/*.yaml",
            f"**/{_DEFAULT_SEMGREP_CONFIG_DIR}/**/*.yml",
        )
    elif semgrep.config_name.endswith((".yaml", ".yml")):
        config_file_globs = (f"**/{semgrep.config_name}",)
    else:
        config_dir_globs = (
            f"**/{semgrep.config_name}/**/*.yaml",
            f"**/{semgrep.config_name}/**/*.yml",
        )

    all_config_files = await path_globs_to_paths(config_file_globs)
    all_config_dir_files = await path_globs_to_paths(config_dir_globs)
    return _group_by_semgrep_dir(
        all_config_files,
        all_config_dir_files,
        (semgrep.config_name or _DEFAULT_SEMGREP_CONFIG_DIR),
    )


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

    all_configs = await concurrently(
        infer_relevant_semgrep_configs(RelevantSemgrepConfigsRequest(field_set), **implicitly())
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
    config_files, ignore_files, semgrep_pex, input_files, settings = await concurrently(
        digest_to_snapshot(
            **implicitly(PathGlobs(str(s) for s in request.partition_metadata.config_files))
        ),
        digest_to_snapshot(**implicitly(PathGlobs([_SEMGREPIGNORE_FILE_NAME]))),
        create_venv_pex(**implicitly(semgrep.to_pex_request())),
        determine_source_files(
            SourceFilesRequest(field_set.source for field_set in request.elements)
        ),
        create_digest_to_digest(CreateDigest([_DEFAULT_SETTINGS])),
    )

    input_digest = await merge_digests_request_to_digest(
        MergeDigests(
            (
                input_files.snapshot.digest,
                config_files.digest,
                settings,
                ignore_files.digest,
            )
        )
    )

    cache_scope = ProcessCacheScope.PER_SESSION if semgrep.force else ProcessCacheScope.SUCCESSFUL

    # TODO: https://github.com/pantsbuild/pants/issues/18430 support running this with --autofix
    # under the fix goal... but not all rules have fixes, so we need to be running with
    # --error/checking exit codes, which FixResult doesn't currently support.
    result = await process_request_to_process_result(
        **implicitly(
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
            )
        )
    )

    return LintResult.create(request, result, output_simplifier=global_options.output_simplifier())


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *SemgrepLintRequest.rules(), *pex.rules()]
