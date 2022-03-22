# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.backend.helm.resolve import artifacts
from pants.backend.helm.resolve.artifacts import ThirdPartyArtifactMapping
from pants.backend.helm.subsystems import helm
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import AllHelmChartTargets, HelmChartMetaSourceField
from pants.backend.helm.util_rules.chart import HelmChartMetadata
from pants.engine.addresses import Address, Addresses
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


class InferHelmChartDependenciesRequest(InferDependenciesRequest):
    infer_from = HelmChartMetaSourceField


@rule(desc="Inferring Helm chart dependencies", level=LogLevel.DEBUG)
async def infer_chart_dependencies_via_metadata(
    request: InferHelmChartDependenciesRequest,
    all_chart_tgts: AllHelmChartTargets,
    third_party_mapping: ThirdPartyArtifactMapping,
    subsystem: HelmSubsystem,
) -> InferredDependencies:
    # Build a mapping between the available Helm chart targets and their names
    first_party_chart_mapping: dict[str, Addresses] = {}
    for tgt in all_chart_tgts:
        first_party_chart_mapping[tgt.address.target_name] = tgt.address

    # Parse Chart.yaml for explicitly set dependencies
    metadata = await Get(HelmChartMetadata, HelmChartMetaSourceField, request.sources_field)

    # Associate dependencies in Chart.yaml with addresses
    dependencies: OrderedSet[Address] = OrderedSet()
    for chart_dep in metadata.dependencies:
        # Check if this is a third party dependency declared as `helm_artifact`
        artifact_addr = third_party_mapping.get(chart_dep.remote_spec(subsystem.remotes()))
        if artifact_addr:
            dependencies.add(artifact_addr)
            continue

        # Treat the dependency as a first party one
        dependencies.add(first_party_chart_mapping[chart_dep.name])

    logger.debug(
        f"Inferred {pluralize(len(dependencies), 'dependency')} for target at address: {request.sources_field.address}"
    )
    return InferredDependencies(dependencies)


def rules():
    return [
        *collect_rules(),
        *artifacts.rules(),
        *helm.rules(),
        UnionRule(InferDependenciesRequest, InferHelmChartDependenciesRequest),
    ]
