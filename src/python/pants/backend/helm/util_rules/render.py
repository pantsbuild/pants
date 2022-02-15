# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping

from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_SNAPSHOT, RemovePrefix, Snapshot
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@frozen_after_init
@dataclass(unsafe_hash=True)
class RenderChartRequest:
    chart: HelmChart
    api_versions: tuple[str, ...]
    kube_version: str | None
    skip_tests: bool
    value_files: Snapshot
    values: FrozenDict[str, str]

    def __init__(
        self,
        chart: HelmChart,
        *,
        api_versions: Iterable[str] = [],
        kube_version: str | None = None,
        skip_tests: bool = True,
        value_files: Snapshot = EMPTY_SNAPSHOT,
        values: Mapping[str, str] = {},
    ) -> None:
        self.chart = chart
        self.api_versions = tuple(api_versions)
        self.kube_version = kube_version
        self.skip_tests = skip_tests
        self.value_files = value_files
        self.values = FrozenDict(values)


class FailedRenderingChartException(Exception):
    def __init__(self, request: RenderChartRequest, msg: str) -> None:
        super().__init__(f"Could not render Helm chart '{request.chart.metadata.name}':\n\n{msg}")


@dataclass(frozen=True)
class RenderedChart:
    address: Address
    snapshot: Snapshot


@rule(desc="Render Helm chart", level=LogLevel.DEBUG)
async def render_templates(request: RenderChartRequest, helm: HelmBinary) -> RenderedChart:
    output_prefix = "__output"

    result = await Get(
        FallibleProcessResult,
        Process,
        helm.template(
            release_name=request.chart.metadata.name,
            path=request.chart.path,
            chart_digest=request.chart.snapshot.digest,
            output_dir=output_prefix,
            api_versions=request.api_versions,
            kube_version=request.kube_version,
            skip_tests=request.skip_tests,
            value_files=request.value_files,
            values=request.values,
        ),
    )

    if result.exit_code != 0:
        error_msg = result.stderr.decode()
        raise FailedRenderingChartException(request, error_msg)

    output_snapshot = await Get(Snapshot, RemovePrefix(result.output_digest, output_prefix))
    return RenderedChart(address=request.chart.address, snapshot=output_snapshot)


def rules():
    return collect_rules()
