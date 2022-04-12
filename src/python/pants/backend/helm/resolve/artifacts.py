# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, cast

from pants.backend.helm.resolve.remotes import HelmRemotes
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import (
    AllHelmArtifactTargets,
    AllHelmChartTargets,
    HelmArtifactFieldSet,
    HelmArtifactRegistryField,
    HelmArtifactRepositoryField,
    HelmChartMetaSourceField,
    HelmChartTarget,
)
from pants.backend.helm.util_rules.chart_metadata import HelmChartMetadata
from pants.backend.helm.util_rules.chart_metadata import rules as metadata_rules
from pants.engine.addresses import Address
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_method
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import bullet_list


class MissingHelmArtifactLocation(ValueError):
    def __init__(self, address: Address) -> None:
        super().__init__(
            f"Target at address '{address}' needs to specify either `{HelmArtifactRegistryField.alias}`, "
            f"`{HelmArtifactRepositoryField.alias}` or both."
        )


class DuplicateHelmChartNamesFound(Exception):
    def __init__(self, duplicates: Iterable[tuple[str, Address]]) -> None:
        super().__init__(
            f"Found more than one `{HelmChartTarget.alias}` target using the same chart name:\n\n"
            f"{bullet_list([f'{addr} -> {name}' for name, addr in duplicates])}"
        )


@dataclass(frozen=True)
class HelmArtifactRegistryLocation:
    registry: str
    repository: str | None


@dataclass(frozen=True)
class HelmArtifactClassicRepositoryLocation:
    repository: str


@dataclass(frozen=True)
class HelmArtifactRequirement:
    name: str
    version: str
    location: HelmArtifactRegistryLocation | HelmArtifactClassicRepositoryLocation


@dataclass(frozen=True)
class HelmArtifact:
    requirement: HelmArtifactRequirement
    address: Address

    @classmethod
    def from_target(cls, target: Target) -> HelmArtifact:
        return cls.from_field_set(HelmArtifactFieldSet.create(target))

    @classmethod
    def from_field_set(cls, field_set: HelmArtifactFieldSet) -> HelmArtifact:
        registry = field_set.registry.value
        repository = field_set.repository.value
        if not registry and not repository:
            raise MissingHelmArtifactLocation(field_set.address)

        registry_location: HelmArtifactRegistryLocation | None = None
        if registry:
            registry_location = HelmArtifactRegistryLocation(registry, repository)

        location = registry_location or HelmArtifactClassicRepositoryLocation(cast(str, repository))
        req = HelmArtifactRequirement(
            name=cast(str, field_set.artifact.value),
            version=cast(str, field_set.version.value),
            location=location,
        )

        return cls(requirement=req, address=field_set.address)

    @property
    def name(self) -> str:
        return self.requirement.name

    @memoized_method
    def remote_address(self, remotes: HelmRemotes) -> str:
        if isinstance(self.requirement.location, HelmArtifactRegistryLocation):
            remote = next(remotes.get(self.requirement.location.registry))
            repo_ref = f"{remote.address}/{self.requirement.location.repository or ''}".rstrip("/")
        else:
            remote = next(remotes.get(self.requirement.location.repository))
            repo_ref = remote.alias

        return f"{repo_ref}/{self.name}"


class FirstPartyArtifactMapping(FrozenDict[str, Address]):
    pass


@rule
async def first_party_artifact_mapping(
    all_helm_chart_tgts: AllHelmChartTargets,
) -> FirstPartyArtifactMapping:
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

    return FirstPartyArtifactMapping(name_addr_mapping)


class ThirdPartyArtifactMapping(FrozenDict[str, Address]):
    pass


@rule
def third_party_artifact_mapping(
    all_helm_artifact_tgts: AllHelmArtifactTargets, subsystem: HelmSubsystem
) -> ThirdPartyArtifactMapping:
    artifacts = [HelmArtifact.from_target(tgt) for tgt in all_helm_artifact_tgts]
    return ThirdPartyArtifactMapping(
        {artifact.remote_address(subsystem.remotes()): artifact.address for artifact in artifacts}
    )


def rules():
    return [*collect_rules(), *metadata_rules()]
