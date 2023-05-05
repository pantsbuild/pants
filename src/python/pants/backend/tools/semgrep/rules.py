# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import Partition, Partitions
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests, PathGlobs, Snapshot
from pants.engine.process import FallibleProcessResult, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, Rule, collect_rules, rule
from pants.engine.target import AllTargets, Target, Targets
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

from .subsystem import SemgrepFieldSet, SemgrepSubsystem
from .target_types import SemgrepRuleSourceField

logger = logging.getLogger(__name__)


class SemgrepLintRequest(LintTargetsRequest):
    field_set_type = SemgrepFieldSet
    tool_subsystem = SemgrepSubsystem


@dataclass(frozen=True)
class PartitionMetadata:
    config_files: frozenset[SemgrepRuleSourceField]
    ignore_files: Snapshot

    @property
    def description(self) -> str:
        return ", ".join(sorted(field.file_path for field in self.config_files))


_IGNORE_FILE_NAME = ".semgrepignore"


@dataclass
class SemgrepIgnoreFiles:
    snapshot: Snapshot


@dataclass
class AllSemgrepConfigs:
    targets: dict[str, list[Target]]

    def ancestor_targets(self, address: Address) -> Iterable[Target]:
        # TODO: introspect the semgrep rules and determine which (if any) apply to the files, e.g. a
        # Python file shouldn't depend on a .semgrep.yml that doesn't have any 'python' or 'generic'
        # rules, and similarly if there's path inclusions/exclusions.
        # TODO: this would be better as actual dependency inference (e.g. allows inspection, manual
        # addition/exclusion), but that can only infer 'full' dependencies and it is wrong (e.g. JVM
        # things break) for real code files to depend on this sort of non-code linter config; requires
        # dependency scopes or similar (https://github.com/pantsbuild/pants/issues/12794)
        spec = Path(address.spec_path)

        for ancestor in itertools.chain([spec], spec.parents):
            spec_path = str(ancestor)
            yield from self.targets.get("" if spec_path == "." else spec_path, [])


@rule
async def find_all_semgrep_configs(all_targets: AllTargets) -> AllSemgrepConfigs:
    targets = defaultdict(list)
    for tgt in all_targets:
        if tgt.has_field(SemgrepRuleSourceField):
            targets[tgt.address.spec_path].append(tgt)
    return AllSemgrepConfigs(targets)


@dataclass(frozen=True)
class InferSemgrepDependenciesRequest:
    field_set: SemgrepFieldSet


@rule
async def infer_semgrep_dependencies(
    request: InferSemgrepDependenciesRequest, all_semgrep: AllSemgrepConfigs
) -> Targets:
    return Targets(tuple(all_semgrep.ancestor_targets(request.field_set.address)))


@rule
async def all_semgrep_ignore_files() -> SemgrepIgnoreFiles:
    snapshot = await Get(Snapshot, PathGlobs([f"**/{_IGNORE_FILE_NAME}"]))
    return SemgrepIgnoreFiles(snapshot)


@rule
async def partition(
    request: SemgrepLintRequest.PartitionRequest[SemgrepFieldSet],
    semgrep: SemgrepSubsystem,
    ignore_files: SemgrepIgnoreFiles,
) -> Partitions:
    if semgrep.skip:
        return Partitions()

    dependencies = await MultiGet(
        Get(Targets, InferSemgrepDependenciesRequest(field_set)) for field_set in request.field_sets
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
    request: SemgrepLintRequest.Batch[SemgrepFieldSet, PartitionMetadata],
    semgrep: SemgrepSubsystem,
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
                *(f"--config={f}" for f in config_files.snapshot.files),
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

    return LintResult.create(request, result, strip_formatting=not global_options.colors)


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *SemgrepLintRequest.rules(), *pex.rules()]
