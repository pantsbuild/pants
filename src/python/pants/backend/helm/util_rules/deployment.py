# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartTarget,
    HelmDeploymentFieldSet,
)
from pants.backend.helm.util_rules import chart
from pants.backend.helm.util_rules.chart import HelmChartRequest
from pants.engine.addresses import Address, Addresses
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import DependenciesRequest, ExplicitlyProvidedDependencies, Targets


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


def rules():
    return [*collect_rules(), *chart.rules()]
