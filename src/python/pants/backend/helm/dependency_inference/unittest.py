# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.helm.target_types import AllHelmChartTargets, HelmUnitTestChartField
from pants.engine.addresses import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies, Target
from pants.engine.unions import UnionRule


class InvalidUnitTestTestFolder(Exception):
    def __init__(self, address: Address, found_folder: str) -> None:
        super().__init__(
            f"`helm_unittest_test` target at {address.spec_path} is at the wrong folder, "
            "it should be inside a `tests` folder under the Helm chart root sources but it was found at: {found_folder}"
        )


class InjectHelmUnitTestChartDependencyRequest(InjectDependenciesRequest):
    inject_for = HelmUnitTestChartField


@rule
async def inject_chart_dependency_into_unittests(
    request: InjectHelmUnitTestChartDependencyRequest, all_helm_charts: AllHelmChartTargets
) -> InjectedDependencies:
    unittest_target_addr: Address = request.dependencies_field.address

    unittest_target_relpath = os.path.splitext(unittest_target_addr.spec_path)[0]
    if unittest_target_relpath != "tests" and os.path.dirname(unittest_target_relpath) != "tests":
        raise InvalidUnitTestTestFolder(unittest_target_addr, unittest_target_relpath)

    putative_chart_path = os.path.splitext(unittest_target_relpath)[0]

    def is_parent_chart(target: Target) -> bool:
        chart_folder = os.path.dirname(target.address.spec_path)
        return chart_folder == putative_chart_path or target.address.spec_path == ""

    parent_chart_addrs = [tgt.address for tgt in all_helm_charts if is_parent_chart(tgt)]
    return InjectedDependencies(parent_chart_addrs)


def rules():
    return [
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectHelmUnitTestChartDependencyRequest),
    ]
