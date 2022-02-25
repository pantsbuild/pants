# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pants.backend.helm.subsystem import HelmSubsystem
from pants.backend.helm.target_types import (
    HelmArtifactFieldSet,
    HelmArtifactRegistryField,
    HelmArtifactRepositoryField,
    HelmArtifactVersionField,
)
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.rules import collect_rules, rule
from pants.engine.target import AllTargets, Target, Targets
from pants.util.frozendict import FrozenDict


class InvalidRegistryError(ValueError):
    pass


class InvalidRepositoryError(ValueError):
    pass


class InvalidHelmArtifactError(ValueError):
    pass


class AllHelmArtifactTargets(Targets):
    pass


@dataclass(frozen=True)
class RegistryLocation:
    registry: str
    repository: str | None = None

    def __repr__(self) -> str:
        return f"{self.registry}/{self.repository}".rstrip("/")


@dataclass(frozen=True)
class RepositoryLocation:
    repository: str

    def __repr__(self) -> str:
        return self.repository


@dataclass(frozen=True)
class HelmArtifact:
    name: str
    version: str
    address: Address
    location: RegistryLocation | RepositoryLocation

    @classmethod
    def from_target(cls, target: Target) -> HelmArtifact:
        return cls.from_field_set(HelmArtifactFieldSet.create(target))

    @classmethod
    def from_field_set(cls, field_set: HelmArtifactFieldSet) -> HelmArtifact:
        registry = field_set.registry.value
        repository = field_set.repository.value
        if not registry and not repository:
            raise InvalidHelmArtifactError(
                f"Target at address '{field_set.address}' needs to specify either `{HelmArtifactRegistryField.alias}`, "
                f"`{HelmArtifactRepositoryField.alias}` or both."
            )

        reg_loc: RegistryLocation | None = None
        if registry:
            reg_loc = RegistryLocation(registry, repository)

        return cls(
            name=cast("str", field_set.artifact.value),
            version=cast("str", field_set.version.value),
            address=field_set.address,
            location=reg_loc or RepositoryLocation(cast("str", repository)),
        )

    @property
    def location_str(self) -> str:
        loc: str | None = None
        if isinstance(self.location, RegistryLocation):
            loc = f"{self.location.registry}/{self.location.repository or ''}".rstrip("/")
        else:
            loc = self.location.repository
        return f"{loc}/{self.name}"

    def __repr__(self) -> str:
        return f"{self.location}/{self.name}@{self.version}"


class HelmArtifacts(Collection[HelmArtifact]):
    pass


class AllThirdPartyArtifacts(HelmArtifacts):
    pass


class ThirdPartyArtifactMapping(FrozenDict[str, Address]):
    pass


@rule
def all_helm_artifact_targets(all_targets: AllTargets) -> AllHelmArtifactTargets:
    return AllHelmArtifactTargets(
        [tgt for tgt in all_targets if tgt.has_field(HelmArtifactVersionField)]
    )


@rule
def all_third_party_helm_artifacts(targets: AllHelmArtifactTargets) -> AllThirdPartyArtifacts:
    return AllThirdPartyArtifacts([HelmArtifact.from_target(tgt) for tgt in targets])


@rule
def third_party_helm_artifact_mapping(
    all_targets: AllHelmArtifactTargets, config: HelmSubsystem
) -> ThirdPartyArtifactMapping:
    artifacts = [HelmArtifact.from_target(tgt) for tgt in all_targets]
    return ThirdPartyArtifactMapping(
        {artifact.location_str: artifact.address for artifact in artifacts}
    )


def rules():
    return collect_rules()
