# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from itertools import chain

from pants.backend.helm.subsystems import post_renderer
from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartTarget,
    HelmDeploymentFieldSet,
)
from pants.backend.helm.util_rules import chart, process
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartRequest
from pants.backend.helm.util_rules.process import HelmRenderCmd, HelmRenderProcess
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import RemovePrefix, Snapshot
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, ExplicitlyProvidedDependencies, Targets
from pants.util.logging import LogLevel


class MissingHelmDeploymentChartError(ValueError):
    def __init__(self, address: Address) -> None:
        super().__init__(
            f"The target '{address}' is missing a dependency on a `{HelmChartTarget.alias}` target."
        )


class TooManyChartDependenciesError(ValueError):
    def __init__(self, address: Address) -> None:
        super().__init__(
            f"The target '{address}' has too many `{HelmChartTarget.alias}` "
            "addresses in its dependencies, it should have only one."
        )


@dataclass(frozen=True)
class FindHelmDeploymentChart:
    field_set: HelmDeploymentFieldSet


@rule
async def get_chart_of_deployment(request: FindHelmDeploymentChart) -> HelmChartRequest:
    explicit_dependencies = await Get(
        ExplicitlyProvidedDependencies, DependenciesRequest(request.field_set.dependencies)
    )
    explicit_targets = await Get(
        Targets,
        Addresses(
            [
                addr
                for addr in explicit_dependencies.includes
                if addr not in explicit_dependencies.ignores
            ]
        ),
    )

    found_charts = [tgt for tgt in explicit_targets if HelmChartFieldSet.is_applicable(tgt)]
    if not found_charts:
        raise MissingHelmDeploymentChartError(request.field_set.address)
    if len(found_charts) > 1:
        raise TooManyChartDependenciesError(request.field_set.address)

    return HelmChartRequest.from_target(found_charts[0])


@dataclass(frozen=True)
class RenderHelmDeploymentRequest:
    field_set: HelmDeploymentFieldSet
    api_versions: tuple[str, ...] = ()
    kube_version: str | None = None


@dataclass(frozen=True)
class RenderedDeployment:
    address: Address
    snapshot: Snapshot


@rule(desc="Render Helm deployment", level=LogLevel.DEBUG)
async def render_helm_deployment(request: RenderHelmDeploymentRequest) -> RenderedDeployment:
    output_dir = "__output"

    chart, value_files = await MultiGet(
        Get(HelmChart, FindHelmDeploymentChart(request.field_set)),
        Get(StrippedSourceFiles, SourceFilesRequest([request.field_set.sources])),
    )

    release_name = request.field_set.release_name.value or request.field_set.address.target_name
    result = await Get(
        ProcessResult,
        HelmRenderProcess(
            cmd=HelmRenderCmd.TEMPLATE,
            release_name=release_name,
            chart_path=chart.path,
            chart_digest=chart.snapshot.digest,
            description=request.field_set.description.value,
            namespace=request.field_set.namespace.value,
            skip_crds=request.field_set.skip_crds.value,
            no_hooks=request.field_set.no_hooks.value,
            values_snapshot=value_files.snapshot,
            values=request.field_set.values.value,
            extra_argv=[
                *(("--kube-version", request.kube_version) if request.kube_version else ()),
                *chain.from_iterable(
                    [("--api-versions", api_version) for api_version in request.api_versions]
                ),
                "--output-dir",
                output_dir,
            ],
            message=f"Rendering Helm deployment {request.field_set.address}",
            output_directory=output_dir,
        ),
    )

    output_snapshot = await Get(
        Snapshot, RemovePrefix(result.output_digest, os.path.join(output_dir, chart.path))
    )
    return RenderedDeployment(address=request.field_set.address, snapshot=output_snapshot)


def rules():
    return [*collect_rules(), *chart.rules(), *process.rules(), *post_renderer.rules()]
