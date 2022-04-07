# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.backend.helm.resolve import artifacts
from pants.backend.helm.resolve.artifacts import (
    FirstPartyArtifactMapping,
    ThirdPartyArtifactMapping,
)
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import HelmChartDependenciesField, HelmChartMetaSourceField
from pants.backend.helm.util_rules.chart_metadata import HelmChartDependency, HelmChartMetadata
from pants.engine.addresses import Address
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferDependenciesRequest,
    InferredDependencies,
    WrappedTarget,
)
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
    original_addr = request.sources_field.address
    wrapped_tgt = await Get(WrappedTarget, Address, original_addr)
    tgt = wrapped_tgt.target

    # Parse Chart.yaml for explicitly set dependencies.
    explicitly_provided_deps, metadata = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(tgt[HelmChartDependenciesField])),
        Get(HelmChartMetadata, HelmChartMetaSourceField, request.sources_field),
    )

    # Associate dependencies in Chart.yaml with addresses.
    dependencies: OrderedSet[Address] = OrderedSet()
    for chart_dep in metadata.dependencies:
        candidate_addrs = []

        first_party_dep = first_party_mapping.get(chart_dep.name)
        if first_party_dep:
            candidate_addrs.append(first_party_dep)

        third_party_dep = third_party_mapping.get(chart_dep.remote_spec(subsystem.remotes()))
        if third_party_dep:
            candidate_addrs.append(third_party_dep)

        if not candidate_addrs:
            raise UnknownHelmChartDependency(original_addr, chart_dep)

        matches = frozenset(candidate_addrs).difference(explicitly_provided_deps.includes)

        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            matches,
            original_addr,
            context=f"The Helm chart {original_addr} declares `{chart_dep.name}` as dependency",
            import_reference="helm dependency",
        )

        maybe_disambiguated = explicitly_provided_deps.disambiguated(matches)
        if maybe_disambiguated:
            dependencies.add(maybe_disambiguated)

    logger.debug(
        f"Inferred {pluralize(len(dependencies), 'dependency')} for target at address: {request.sources_field.address}"
    )
    return InferredDependencies(dependencies)


def rules():
    return [
        *collect_rules(),
        *artifacts.rules(),
        UnionRule(InferDependenciesRequest, InferHelmChartDependenciesRequest),
    ]
