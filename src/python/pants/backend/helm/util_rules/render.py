# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
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
    value_files: Snapshot
    values: FrozenDict[str, str]

    def __init__(
        self,
        chart: HelmChart,
        *,
        value_files: Snapshot = EMPTY_SNAPSHOT,
        values: Mapping[str, str] | None = None,
    ) -> None:
        self.chart = chart
        self.value_files = value_files
        self.values = FrozenDict(values or {})


@dataclass(frozen=True)
class RenderedHelmChart:
    snapshot: Snapshot


def _sort_value_file_names(filenames: Iterable[str]) -> list[str]:
    """Breaks the list of files into two main buckets: overrides and non-overrides, and then sorts
    each of the buckets using a path-based criteria.

    The final list will be composed by the non-overrides bucket followed by the overrides one.
    """

    non_overrides = []
    overrides = []
    paths = map(lambda a: PurePath(a), list(filenames))
    for p in paths:
        if "override" in p.name:
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
        MergeDigests([request.chart.snapshot.digest, request.value_files.digest, empty_output_dir]),
    )

    sorted_value_files = _sort_value_file_names(request.value_files.files)
    inline_values: list[str] = list(
        chain.from_iterable([["--set", f"{key}={value}"] for key, value in request.values.items()])
    )

    result = await Get(
        ProcessResult,
        HelmProcess(
            argv=[
                "template",
                request.chart.metadata.name,
                request.chart.path,
                "--values",
                ",".join(sorted_value_files),
                *inline_values,
                "--output-dir",
                output_dir,
            ],
            input_digest=input_digest,
            description=f"Rendering Helm chart {request.chart.address}...",
            level=LogLevel.DEBUG,
            output_directories=(output_dir,),
        ),
    )

    output_snapshot = await Get(Snapshot, RemovePrefix(result.output_digest, output_dir))
    return RenderedHelmChart(snapshot=output_snapshot)


def rules():
    return collect_rules()
