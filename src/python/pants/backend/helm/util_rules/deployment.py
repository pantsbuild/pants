# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartTarget,
    HelmDeploymentFieldSet,
)
from pants.backend.helm.util_rules import chart, render
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartRequest
from pants.backend.helm.util_rules.render import RenderedHelmChart, RenderHelmChartRequest
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import Snapshot
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


@rule
async def get_chart_of_deployment(field_set: HelmDeploymentFieldSet) -> HelmChartRequest:
    explicit_dependencies = await Get(
        ExplicitlyProvidedDependencies, DependenciesRequest(field_set.dependencies)
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
        raise MissingHelmDeploymentChartError(field_set.address)
    if len(found_charts) > 1:
        raise TooManyChartDependenciesError(field_set.address)

    return HelmChartRequest.from_target(found_charts[0])


@dataclass(frozen=True)
class RenderHelmDeploymentRequest:
    field_set: HelmDeploymentFieldSet


@dataclass(frozen=True)
class RenderedDeployment:
    address: Address
    snapshot: Snapshot


@rule(desc="Render Helm deployment", level=LogLevel.DEBUG)
async def render_helm_deployment(request: RenderHelmDeploymentRequest) -> RenderedDeployment:
    chart, value_files = await MultiGet(
        Get(HelmChart, HelmDeploymentFieldSet, request.field_set),
        Get(StrippedSourceFiles, SourceFilesRequest([request.field_set.sources])),
    )

    rendered_chart = await Get(
        RenderedHelmChart,
        RenderHelmChartRequest(
            chart,
            description=request.field_set.description.value,
            namespace=request.field_set.namespace.value,
            skip_crds=request.field_set.skip_crds.value,
            no_hooks=request.field_set.no_hooks.value,
            values_snapshot=value_files.snapshot,
            values=request.field_set.values.value,
        ),
    )
    return RenderedDeployment(address=request.field_set.address, snapshot=rendered_chart.snapshot)


def rules():
    return [*collect_rules(), *chart.rules(), *render.rules()]
