# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from itertools import chain
from pathlib import PurePath
from typing import Iterable, Mapping

from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    CreateDigest,
    Digest,
    Directory,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@frozen_after_init
@dataclass(unsafe_hash=True)
class RenderHelmChartRequest:
    chart: HelmChart
    values_snapshot: Snapshot
    values: FrozenDict[str, str]
    skip_crds: bool
    no_hooks: bool
    description: str | None = field(compare=False)
    namespace: str | None
    api_versions: tuple[str, ...]
    kube_version: str | None

    def __init__(
        self,
        chart: HelmChart,
        *,
        description: str | None = None,
        namespace: str | None = None,
        api_versions: Iterable[str] | None = None,
        kube_version: str | None = None,
        skip_crds: bool = False,
        no_hooks: bool = False,
        values_snapshot: Snapshot = EMPTY_SNAPSHOT,
        values: Mapping[str, str] | None = None,
    ) -> None:
        self.chart = chart
        self.description = description
        self.namespace = namespace
        self.api_versions = tuple(api_versions or ())
        self.kube_version = kube_version
        self.skip_crds = skip_crds
        self.no_hooks = no_hooks
        self.values_snapshot = values_snapshot
        self.values = FrozenDict(values or {})


@dataclass(frozen=True)
class RenderedHelmChart:
    snapshot: Snapshot


def sort_value_file_names_for_rendering(filenames: Iterable[str]) -> list[str]:
    """Breaks the list of files into two main buckets: overrides and non-overrides, and then sorts
    each of the buckets using a path-based criteria.

    The final list will be composed by the non-overrides bucket followed by the overrides one.
    """

    non_overrides = []
    overrides = []
    paths = map(lambda a: PurePath(a), list(filenames))
    for p in paths:
        if "override" in p.name.lower():
            overrides.append(p)
        else:
            non_overrides.append(p)

    def by_path_length(p: PurePath) -> int:
        if not p.parents:
            return 0
        return len(p.parents)

    non_overrides.sort(key=by_path_length)
    overrides.sort(key=by_path_length)
    return list(map(lambda a: str(a), [*non_overrides, *overrides]))


@rule(desc="Render Helm chart", level=LogLevel.DEBUG)
async def render_helm_chart(request: RenderHelmChartRequest) -> RenderedHelmChart:
    output_dir = "__output"

    empty_output_dir = await Get(Digest, CreateDigest([Directory(output_dir)]))
    input_digest = await Get(
        Digest,
        MergeDigests(
            [request.chart.snapshot.digest, request.values_snapshot.digest, empty_output_dir]
        ),
    )

    sorted_value_files = sort_value_file_names_for_rendering(request.values_snapshot.files)

    result = await Get(
        ProcessResult,
        HelmProcess(
            argv=[
                "template",
                request.chart.metadata.name,
                request.chart.path,
                *(("--description", f'"{request.description}"') if request.description else ()),
                *(("--namespace", request.namespace) if request.namespace else ()),
                *(("--kube-version", request.kube_version) if request.kube_version else ()),
                *chain.from_iterable(
                    [("--api-versions", api_version) for api_version in request.api_versions]
                ),
                *(("--skip-crds",) if request.skip_crds else ()),
                *(("--no-hooks",) if request.no_hooks else ()),
                *(("--values", ",".join(sorted_value_files)) if sorted_value_files else ()),
                *chain.from_iterable(
                    [("--set", f"{key}={value}") for key, value in request.values.items()]
                ),
                "--output-dir",
                output_dir,
            ],
            input_digest=input_digest,
            description=f"Rendering Helm chart {request.chart.address}...",
            level=LogLevel.DEBUG,
            output_directories=(output_dir,),
        ),
    )

    output_snapshot = await Get(
        Snapshot, RemovePrefix(result.output_digest, os.path.join(output_dir, request.chart.path))
    )
    return RenderedHelmChart(snapshot=output_snapshot)


def rules():
    return collect_rules()
