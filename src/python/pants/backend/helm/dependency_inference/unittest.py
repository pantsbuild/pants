# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from typing import Sequence

from pants.backend.helm.target_types import AllHelmChartTargets, HelmUnitTestDependenciesField
from pants.engine.addresses import Address
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    Target,
)
from pants.engine.unions import UnionRule
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import bullet_list, pluralize

logger = logging.getLogger(__name__)


class InvalidUnitTestTestFolder(Exception):
    def __init__(self, address: Address, found_folder: str) -> None:
        super().__init__(
            f"`helm_unittest_test` target at {address.spec_path} is at the wrong folder, "
            f"it should be inside a `tests` folder under the Helm chart root sources, it was found at: {found_folder}"
        )


class AmbiguousHelmUnitTestChart(Exception):
    def __init__(self, *, target_addr: str, putative_addresses: Sequence[str]) -> None:
        super().__init__(
            f"The actual Helm chart for the target at '{target_addr}' is ambiguous and can not be inferred. "
            f"Found {pluralize(len(putative_addresses), 'candidate')}:\n{bullet_list(putative_addresses)}"
        )


class InjectHelmUnitTestChartDependencyRequest(InjectDependenciesRequest):
    inject_for = HelmUnitTestDependenciesField


@rule
async def inject_chart_dependency_into_unittests(
    request: InjectHelmUnitTestChartDependencyRequest, all_helm_charts: AllHelmChartTargets
) -> InjectedDependencies:
    unittest_target_addr: Address = request.dependencies_field.address

    putative_chart_path, unittest_target_dir = os.path.split(unittest_target_addr.spec_path)
    if unittest_target_dir != "tests":
        raise InvalidUnitTestTestFolder(unittest_target_addr, unittest_target_addr.spec_path)

    def is_parent_chart(target: Target) -> bool:
        chart_folder = target.address.spec_path
        return chart_folder == putative_chart_path

    candidate_charts: OrderedSet[Address] = OrderedSet(
        [tgt.address for tgt in all_helm_charts if is_parent_chart(tgt)]
    )
    chart_dependencies: OrderedSet[Address] = OrderedSet()

    explicitly_provided_deps = await Get(
        ExplicitlyProvidedDependencies, DependenciesRequest(request.dependencies_field)
    )

    for candidate_chart in candidate_charts:
        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            (candidate_chart,),
            unittest_target_addr,
            import_reference="chart",
            context=f"The target {unittest_target_addr} is nested under the chart {candidate_chart}",
        )
        maybe_disambiguated = explicitly_provided_deps.disambiguated((candidate_chart,))
        if maybe_disambiguated:
            chart_dependencies.add(maybe_disambiguated)

    if len(chart_dependencies) > 1:
        raise AmbiguousHelmUnitTestChart(
            target_addr=unittest_target_addr.spec,
            putative_addresses=[addr.spec for addr in chart_dependencies],
        )

    if len(chart_dependencies) == 1:
        found_dep = list(chart_dependencies)[0]
        logger.debug(
            f"Found Helm chart at '{found_dep.spec}' for unittest at: {unittest_target_addr.spec}"
        )

    return InjectedDependencies(chart_dependencies)


def rules():
    return [
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectHelmUnitTestChartDependencyRequest),
    ]
