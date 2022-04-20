# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from itertools import chain

from pants.backend.helm.target_types import HelmChartTarget
from pants.backend.helm.util_rules.chart_metadata import HELM_CHART_METADATA_FILENAMES
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeHelmChartTargetsRequest(PutativeTargetsRequest):
    pass


@rule(desc="Determine candidate Helm chart targets to create", level=LogLevel.DEBUG)
async def find_putative_helm_targets(
    request: PutativeHelmChartTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    found_chart_paths = await MultiGet(
        Get(Paths, PathGlobs, request.search_paths.path_globs(filename))
        for filename in HELM_CHART_METADATA_FILENAMES
    )
    all_chart_files = chain.from_iterable([p.files for p in found_chart_paths])
    unowned_chart_files = set(all_chart_files) - set(all_owned_sources)

    putative_targets = []
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

    return PutativeTargets(putative_targets)


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeHelmChartTargetsRequest)]
