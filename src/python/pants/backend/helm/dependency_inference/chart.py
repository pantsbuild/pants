# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.backend.helm.resolve import artifacts
from pants.backend.helm.resolve.artifacts import FirstPartyArtifactMapping, ThirdPartyArtifactMapping
from pants.backend.helm.subsystems import helm
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import AllHelmChartTargets, HelmChartMetaSourceField
from pants.backend.helm.util_rules.chart import HelmChartDependency, HelmChartMetadata
from pants.engine.addresses import Address
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)

class UnknownHelmChartDependency(Exception):
    def __init__(self, address: Address, dependency: HelmChartDependency) -> None:
        super().__init__(
            f"Can not find any declared artifact for dependency '{dependency.name}' "
            f"declared at `Chart.yaml` in Helm chart at address: {address}"
        )

class InferHelmChartDependenciesRequest(InferDependenciesRequest):
    infer_from = HelmChartMetaSourceField


@rule(desc="Inferring Helm chart dependencies", level=LogLevel.DEBUG)
async def infer_chart_dependencies_via_metadata(
    request: InferHelmChartDependenciesRequest,
    first_party_mapping: FirstPartyArtifactMapping,
    third_party_mapping: ThirdPartyArtifactMapping,
    subsystem: HelmSubsystem,
) -> InferredDependencies:
    # Parse Chart.yaml for explicitly set dependencies.
    metadata = await Get(HelmChartMetadata, HelmChartMetaSourceField, request.sources_field)

    # Associate dependencies in Chart.yaml with addresses.
    dependencies: OrderedSet[Address] = OrderedSet()
    for chart_dep in metadata.dependencies:
        # Check if this is a third party dependency declared as `helm_artifact`.
        artifact_addr = third_party_mapping.get(chart_dep.remote_spec(subsystem.remotes()))
        if artifact_addr:
            dependencies.add(artifact_addr)
            continue

        # Treat the dependency as a first party one.
        first_party_addr = first_party_mapping.get(chart_dep.name)
        if not first_party_addr:
            raise UnknownHelmChartDependency(request.sources_field.address, chart_dep)
        
        dependencies.add(first_party_addr)

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
