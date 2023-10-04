# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Sequence

from pants.backend.helm.goals.tailor import _SNAPSHOT_FOLDER_NAME, _TESTS_FOLDER_NAME
from pants.backend.helm.target_types import AllHelmChartTargets, HelmUnitTestDependenciesField
from pants.core.target_types import AllAssetTargetsByPath
from pants.engine.addresses import Address
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
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


@dataclass(frozen=True)
class HelmUnitTestChartDependencyInferenceFieldSet(FieldSet):
    required_fields = (HelmUnitTestDependenciesField,)

    dependencies: HelmUnitTestDependenciesField


class InferHelmUnitTestChartDependencyRequest(InferDependenciesRequest):
    infer_from = HelmUnitTestChartDependencyInferenceFieldSet


@rule
async def infer_chart_dependency_into_unittests(
    request: InferHelmUnitTestChartDependencyRequest,
    all_helm_charts: AllHelmChartTargets,
    all_asset_targets: AllAssetTargetsByPath,
) -> InferredDependencies:
    unittest_target_addr: Address = request.field_set.address

    putative_chart_path, unittest_target_dir = os.path.split(unittest_target_addr.spec_path)
    if unittest_target_dir != _TESTS_FOLDER_NAME:
        raise InvalidUnitTestTestFolder(unittest_target_addr, unittest_target_addr.spec_path)

    explicitly_provided_deps = await Get(
        ExplicitlyProvidedDependencies, DependenciesRequest(request.field_set.dependencies)
    )

    def is_snapshot_resource(path: PurePath) -> bool:
        if not path.parent:
            return False
        if path.parent.name != _SNAPSHOT_FOLDER_NAME:
            return False
        if not path.parent.parent:
            return False
        return str(path.parent.parent) == unittest_target_addr.spec_path

    candidate_snapshot_resources = {
        tgt.address
        for path, targets in all_asset_targets.resources.items()
        if is_snapshot_resource(path)
        for tgt in targets
    }
    found_snapshots = set()

    for candidate_snapshot in candidate_snapshot_resources:
        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            (candidate_snapshot,),
            unittest_target_addr,
            import_reference="snapshot",
            context=f"The target {candidate_snapshot} is nested under {unittest_target_addr}",
        )

        maybe_disambiguated = explicitly_provided_deps.disambiguated((candidate_snapshot,))
        if maybe_disambiguated:
            found_snapshots.add(maybe_disambiguated)

    def is_parent_chart(target: Target) -> bool:
        chart_folder = target.address.spec_path
        return chart_folder == putative_chart_path

    candidate_charts: OrderedSet[Address] = OrderedSet(
        [tgt.address for tgt in all_helm_charts if is_parent_chart(tgt)]
    )
    found_charts = set()

    for candidate_chart in candidate_charts:
        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            (candidate_chart,),
            unittest_target_addr,
            import_reference="chart",
            context=f"The target {unittest_target_addr} is nested under the chart {candidate_chart}",
        )
        maybe_disambiguated = explicitly_provided_deps.disambiguated((candidate_chart,))
        if maybe_disambiguated:
            found_charts.add(maybe_disambiguated)

    if len(found_charts) > 1:
        raise AmbiguousHelmUnitTestChart(
            target_addr=unittest_target_addr.spec,
            putative_addresses=[addr.spec for addr in found_charts],
        )

    if len(found_charts) == 1:
        found_dep = list(found_charts)[0]
        logger.debug(
            f"Found Helm chart at '{found_dep.spec}' for unittest at: {unittest_target_addr.spec}"
        )

    dependencies: OrderedSet[Address] = OrderedSet()
    dependencies.update(found_snapshots)
    dependencies.update(found_charts)

    return InferredDependencies(dependencies)


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferHelmUnitTestChartDependencyRequest),
    ]
