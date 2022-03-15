# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os

from pants.backend.helm.target_types import AllHelmChartTargets, HelmUnitTestChartField
from pants.engine.addresses import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies, Target
from pants.engine.unions import UnionRule
from pants.util.strutil import bullet_list, pluralize

logger = logging.getLogger(__name__)


class InvalidUnitTestTestFolder(Exception):
    def __init__(self, address: Address, found_folder: str) -> None:
        super().__init__(
            f"`helm_unittest_test` target at {address.spec_path} is at the wrong folder, "
            f"it should be inside a `tests` folder under the Helm chart root sources, it was found at: {found_folder}"
        )


class AmbiguousHelmUnitTestChart(Exception):
    def __init__(self, *, target_addr: str, putative_addresses: list[str]) -> None:
        super().__init__(
            f"The actual Helm chart for the target at '{target_addr}' is ambiguous and can not be inferred. "
            f"Found {pluralize(len(putative_addresses), 'candidate')}:\n{bullet_list(putative_addresses)}"
        )


class InjectHelmUnitTestChartDependencyRequest(InjectDependenciesRequest):
    inject_for = HelmUnitTestChartField


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

    parent_chart_addrs = [tgt.address for tgt in all_helm_charts if is_parent_chart(tgt)]
    if len(parent_chart_addrs) > 1:
        raise AmbiguousHelmUnitTestChart(
            target_addr=unittest_target_addr.spec,
            putative_addresses=[addr.spec for addr in parent_chart_addrs],
        )

    if len(parent_chart_addrs) == 1:
        logger.debug(
            f"Found Helm chart at '{parent_chart_addrs[0].spec}' for unittest at: {unittest_target_addr.spec}"
        )

    return InjectedDependencies(parent_chart_addrs)


def rules():
    return [
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectHelmUnitTestChartDependencyRequest),
    ]
