# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, cast

from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import (
    AllHelmArtifactTargets,
    HelmArtifactFieldSet,
    HelmArtifactRegistryField,
    HelmArtifactRepositoryField,
    HelmChartTarget,
)
from pants.backend.helm.util_rules.chart_metadata import rules as metadata_rules
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target
from pants.util.frozendict import FrozenDict
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


class HelmArtifactLocationSpec(ABC):
    @property
    @abstractmethod
    def spec(self) -> str:
        ...

    @property
    def is_url(self) -> bool:
        return len(self.spec.split("://")) == 2

    @property
    def is_alias(self) -> bool:
        return self.spec.startswith("@")


@dataclass(frozen=True)
class HelmArtifactRegistryLocationSpec(HelmArtifactLocationSpec):
    registry: str
    repository: str | None

    @property
    def spec(self) -> str:
        return self.registry


@dataclass(frozen=True)
class HelmArtifactClassicRepositoryLocationSpec(HelmArtifactLocationSpec):
    repository: str

    @property
    def spec(self) -> str:
        return self.repository


@dataclass(frozen=True)
class HelmArtifactRequirement:
    name: str
    version: str
    location: HelmArtifactLocationSpec


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

        registry_location: HelmArtifactRegistryLocationSpec | None = None
        if registry:
            registry_location = HelmArtifactRegistryLocationSpec(registry.rstrip("/"), repository)

        location = registry_location or HelmArtifactClassicRepositoryLocationSpec(
            cast(str, repository).rstrip("/")
        )
        req = HelmArtifactRequirement(
            name=cast(str, field_set.artifact.value),
            version=cast(str, field_set.version.value),
            location=location,
        )

        return cls(requirement=req, address=field_set.address)

    @property
    def name(self) -> str:
        return self.requirement.name

    @property
    def version(self) -> str:
        return self.requirement.version


@dataclass(frozen=True)
class ResolvedHelmArtifact(HelmArtifact, EngineAwareReturnType):
    location_url: str

    @classmethod
    def from_unresolved(cls, artifact: HelmArtifact, *, location_url: str) -> ResolvedHelmArtifact:
        return cls(
            requirement=artifact.requirement,
            address=artifact.address,
            location_url=location_url,
        )

    @property
    def chart_url(self) -> str:
        return f"{self.location_url}/{self.name}"

    def metadata(self) -> dict[str, Any] | None:
        return {
            "name": self.requirement.name,
            "version": self.requirement.version,
            "location": self.requirement.location.spec,
            "address": self.address.spec,
            "url": self.chart_url,
        }


@rule
def resolved_helm_artifact(
    artifact: HelmArtifact, subsystem: HelmSubsystem
) -> ResolvedHelmArtifact:
    remotes = subsystem.remotes()

    candidate_remotes = list(remotes.get(artifact.requirement.location.spec))
    if candidate_remotes:
        loc_url = candidate_remotes[0].address
        if isinstance(artifact.requirement.location, HelmArtifactRegistryLocationSpec):
            loc_url = f"{loc_url}/{artifact.requirement.location.repository or ''}".rstrip("/")
    else:
        loc_url = artifact.requirement.location.spec

    return ResolvedHelmArtifact.from_unresolved(artifact, location_url=loc_url)


class ThirdPartyHelmArtifactMapping(FrozenDict[str, Address]):
    pass


@rule
async def third_party_helm_artifact_mapping(
    all_helm_artifact_tgts: AllHelmArtifactTargets,
) -> ThirdPartyHelmArtifactMapping:
    artifacts = await MultiGet(
        Get(ResolvedHelmArtifact, HelmArtifact, HelmArtifact.from_target(tgt))
        for tgt in all_helm_artifact_tgts
    )
    return ThirdPartyHelmArtifactMapping(
        {artifact.chart_url: artifact.address for artifact in artifacts}
    )


def rules():
    return [*collect_rules(), *metadata_rules()]
