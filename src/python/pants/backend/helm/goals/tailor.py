# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.helm.target_types import HelmChartTarget
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
    group_by_dir,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.source.filespec import Filespec, matches_filespec
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeHelmChartTargetsRequest(PutativeTargetsRequest):
    pass


def classify_source_files(paths: Iterable[str]) -> dict[type[Target], set[str]]:
    """Returns a dict of target type -> files that belong to targets of that type."""

    def filter_paths(spec: Filespec) -> set[str]:
        return {
            path
            for path in paths
            if os.path.basename(path)
            in set(matches_filespec(spec, paths=[os.path.basename(path) for path in paths]))
        }

    chart_filespec = Filespec(includes=["Chart.yaml"])
    chart_files = filter_paths(chart_filespec)

    return {
        HelmChartTarget: chart_files,
    }


@rule(desc="Determine candidate helm_chart targets to create", level=LogLevel.DEBUG)
async def find_putative_targets(
    request: PutativeHelmChartTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    all_chart_files = await Get(Paths, PathGlobs, request.search_paths.path_globs("Chart.yaml"))

    unowned_helm_files = set(all_chart_files.files) - set(all_owned_sources)
    classified_unowned_helm_files = classify_source_files(unowned_helm_files)

    putative_targets = []
    for tgt_type, paths in classified_unowned_helm_files.items():
        for dirname, filenames in group_by_dir(paths).items():
            putative_targets.append(
                PutativeTarget.for_target_type(
                    tgt_type, path=dirname, name=None, triggering_sources=sorted(filenames)
                )
            )

    return PutativeTargets(putative_targets)


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeHelmChartTargetsRequest)]
