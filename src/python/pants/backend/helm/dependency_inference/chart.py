# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from typing import Iterable

from pants.backend.helm.resolve import artifacts
from pants.backend.helm.resolve.artifacts import ThirdPartyHelmArtifactMapping
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import (
    AllHelmChartTargets,
    HelmChartDependenciesField,
    HelmChartMetaSourceField,
    HelmChartTarget,
)
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
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import bullet_list, pluralize

logger = logging.getLogger(__name__)


class DuplicateHelmChartNamesFound(Exception):
    def __init__(self, duplicates: Iterable[tuple[str, Address]]) -> None:
        super().__init__(
            f"Found more than one `{HelmChartTarget.alias}` target using the same chart name:\n\n"
            f"{bullet_list([f'{addr} -> {name}' for name, addr in duplicates])}"
        )


class UnknownHelmChartDependency(Exception):
    def __init__(self, address: Address, dependency: HelmChartDependency) -> None:
        super().__init__(
            f"Can not find any declared artifact for dependency '{dependency.name}' "
            f"declared at `Chart.yaml` in Helm chart at address: {address}"
        )


class FirstPartyHelmChartMapping(FrozenDict[str, Address]):
    pass


@rule
async def first_party_helm_chart_mapping(
    all_helm_chart_tgts: AllHelmChartTargets,
) -> FirstPartyHelmChartMapping:
    charts_metadata = await MultiGet(
        Get(HelmChartMetadata, HelmChartMetaSourceField, tgt[HelmChartMetaSourceField])
        for tgt in all_helm_chart_tgts
    )

    name_addr_mapping: dict[str, Address] = {}
    duplicate_chart_names: OrderedSet[tuple[str, Address]] = OrderedSet()

    for meta, tgt in zip(charts_metadata, all_helm_chart_tgts):
        if meta.name in name_addr_mapping:
            duplicate_chart_names.add((meta.name, name_addr_mapping[meta.name]))
            duplicate_chart_names.add((meta.name, tgt.address))
            continue

        name_addr_mapping[meta.name] = tgt.address

    if duplicate_chart_names:
        raise DuplicateHelmChartNamesFound(duplicate_chart_names)

    return FirstPartyHelmChartMapping(name_addr_mapping)


class InferHelmChartDependenciesRequest(InferDependenciesRequest):
    infer_from = HelmChartMetaSourceField


@rule(desc="Inferring Helm chart dependencies", level=LogLevel.DEBUG)
async def infer_chart_dependencies_via_metadata(
    request: InferHelmChartDependenciesRequest,
    first_party_mapping: FirstPartyHelmChartMapping,
    third_party_mapping: ThirdPartyHelmArtifactMapping,
    subsystem: HelmSubsystem,
) -> InferredDependencies:
    original_addr = request.sources_field.address
    wrapped_tgt = await Get(
        WrappedTarget, WrappedTargetRequest(original_addr, description_of_origin="<infallible>")
    )
    tgt = wrapped_tgt.target

    # Parse Chart.yaml for explicitly set dependencies.
    explicitly_provided_deps, metadata = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(tgt[HelmChartDependenciesField])),
        Get(HelmChartMetadata, HelmChartMetaSourceField, request.sources_field),
    )

    remotes = subsystem.remotes()

    def resolve_dependency_url(dependency: HelmChartDependency) -> str | None:
        if not dependency.repository:
            registry = remotes.default_registry
            if registry:
                return f"{registry.address}/{dependency.name}"
            return None
        else:
            return f"{dependency.repository}/{dependency.name}"

    # Associate dependencies in Chart.yaml with addresses.
    dependencies: OrderedSet[Address] = OrderedSet()
    for chart_dep in metadata.dependencies:
        candidate_addrs = []

        first_party_dep = first_party_mapping.get(chart_dep.name)
        if first_party_dep:
            candidate_addrs.append(first_party_dep)

        dependency_url = resolve_dependency_url(chart_dep)
        third_party_dep = third_party_mapping.get(dependency_url) if dependency_url else None
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
