# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass

from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import (
    HelmChartTarget,
    HelmUnitTestGeneratingSourcesField,
    HelmUnitTestTestsGeneratorTarget,
)
from pants.backend.helm.util_rules.chart_metadata import HELM_CHART_METADATA_FILENAMES
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.core.target_types import ResourcesGeneratorTarget
from pants.engine.fs import PathGlobs, Paths
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.source.filespec import FilespecMatcher
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeHelmTargetsRequest(PutativeTargetsRequest):
    pass


_SNAPSHOT_FOLDER_NAME = "__snapshot__"
_SNAPSHOT_FILE_GLOBS = ("*_test.yaml.snap", "*_test.yml.snap")


@rule(desc="Determine candidate Helm chart targets to create", level=LogLevel.DEBUG)
async def find_putative_helm_targets(
    request: PutativeHelmTargetsRequest,
    all_owned_sources: AllOwnedSources,
    helm_subsystem: HelmSubsystem,
) -> PutativeTargets:
    putative_targets = []

    tailor_charts = helm_subsystem.tailor_charts
    if not tailor_charts and helm_subsystem.options.is_default("tailor_charts"):
        tailor_charts = helm_subsystem.tailor

    if tailor_charts:
        all_chart_files = await Get(
            Paths, PathGlobs, request.path_globs(*HELM_CHART_METADATA_FILENAMES)
        )
        unowned_chart_files = set(all_chart_files.files) - set(all_owned_sources)

        for chart_file in sorted(unowned_chart_files):
            dirname, filename = os.path.split(chart_file)
            putative_targets.append(
                PutativeTarget.for_target_type(
                    HelmChartTarget,
                    name=os.path.basename(dirname),
                    path=dirname,
                    triggering_sources=[filename],
                )
            )

    if helm_subsystem.tailor_unittests:
        all_unittest_files = await Get(
            Paths, PathGlobs, request.path_globs(*HelmUnitTestGeneratingSourcesField.default)
        )
        unonwned_unittest_files = set(all_unittest_files.files) - set(all_owned_sources)
        unittest_filespec_matcher = FilespecMatcher(HelmUnitTestGeneratingSourcesField.default, ())
        unittest_files = {
            path
            for path in unonwned_unittest_files
            if os.path.basename(path)
            in set(
                unittest_filespec_matcher.matches(
                    [os.path.basename(path) for path in unonwned_unittest_files]
                )
            )
        }
        grouped_unittest_files = group_by_dir(unittest_files)

        # To prevent false positives, we look for snapshot files relative to the unit test sources
        all_snapshot_files = await Get(
            Paths,
            PathGlobs(
                [
                    os.path.join(dirname, _SNAPSHOT_FOLDER_NAME, glob)
                    for glob in _SNAPSHOT_FILE_GLOBS
                    for dirname in grouped_unittest_files.keys()
                ]
            ),
        )
        unowned_snapshot_files = set(all_snapshot_files.files) - set(all_owned_sources)
        grouped_snapshot_files = group_by_dir(unowned_snapshot_files)
        snapshot_folders = list(grouped_snapshot_files.keys())

        def find_snapshot_files_for(unittest_dir: str) -> set[str]:
            key = [folder for folder in snapshot_folders if os.path.dirname(folder) == unittest_dir]
            if not key:
                return set()
            return grouped_snapshot_files[key[0]]

        for dirname, filenames in grouped_unittest_files.items():
            putative_targets.append(
                PutativeTarget.for_target_type(
                    HelmUnitTestTestsGeneratorTarget,
                    path=dirname,
                    name=None,
                    triggering_sources=sorted(filenames),
                )
            )

            snapshot_files = find_snapshot_files_for(dirname)
            if snapshot_files:
                putative_targets.append(
                    PutativeTarget.for_target_type(
                        ResourcesGeneratorTarget,
                        path=os.path.join(dirname, _SNAPSHOT_FOLDER_NAME),
                        name=None,
                        triggering_sources=sorted(snapshot_files),
                        kwargs={"sources": _SNAPSHOT_FILE_GLOBS},
                    )
                )

    return PutativeTargets(putative_targets)


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeHelmTargetsRequest)]
