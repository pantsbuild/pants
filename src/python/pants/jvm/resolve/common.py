# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote_plus as url_quote_plus

from pants.engine.collection import DeduplicatedCollection
from pants.engine.target import Target
from pants.jvm.resolve.coordinate import Coordinate
from pants.jvm.target_types import (
    JvmArtifactArtifactField,
    JvmArtifactExclusionsField,
    JvmArtifactFieldSet,
    JvmArtifactForceVersionField,
    JvmArtifactGroupField,
    JvmArtifactJarSourceField,
    JvmArtifactUrlField,
    JvmArtifactVersionField,
)
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class ArtifactRequirement:
    """A single Maven-style coordinate for a JVM dependency, along with information of how to fetch
    the dependency if it is not to be fetched from a Maven repository."""

    coordinate: Coordinate

    url: str | None = None
    jar: JvmArtifactJarSourceField | None = None
    excludes: frozenset[str] | None = None
    force_version: bool = False

    @classmethod
    def from_jvm_artifact_target(cls, target: Target) -> ArtifactRequirement:
        if not JvmArtifactFieldSet.is_applicable(target):
            raise AssertionError(
                "`ArtifactRequirement.from_jvm_artifact_target()` only works on targets with "
                "`JvmArtifactFieldSet` fields present."
            )

        exclusions = target[JvmArtifactExclusionsField].value or ()
        return ArtifactRequirement(
            coordinate=Coordinate(
                group=target[JvmArtifactGroupField].value,
                artifact=target[JvmArtifactArtifactField].value,
                version=target[JvmArtifactVersionField].value,
            ),
            url=target[JvmArtifactUrlField].value,
            jar=(
                target[JvmArtifactJarSourceField]
                if target[JvmArtifactJarSourceField].value
                else None
            ),
            excludes=frozenset([*(exclusion.to_coord_str() for exclusion in exclusions)]) or None,
            force_version=target[JvmArtifactForceVersionField].value,
        )

    def with_extra_excludes(self, *excludes: str) -> ArtifactRequirement:
        """Creates a copy of this `ArtifactRequirement` with `excludes` provided.

        Mostly useful for testing (`Coordinate(...).as_requirement().with_extra_excludes(...)`).
        """

        return dataclasses.replace(
            self, excludes=self.excludes.union(excludes) if self.excludes else frozenset(excludes)
        )

    def to_coord_arg_str(self) -> str:
        return self.coordinate.to_coord_arg_str(
            {"url": url_quote_plus(self.url)} if self.url else {}
        )

    def to_metadata_str(self) -> str:
        attrs = {
            "url": self.url or "not_provided",
            "jar": self.jar.address.spec if self.jar else "not_provided",
        }
        if self.excludes:
            attrs["excludes"] = ",".join(sorted(self.excludes))

        return self.coordinate.to_coord_arg_str(attrs)


# TODO: Consider whether to carry classpath scope in some fashion via ArtifactRequirements.
class ArtifactRequirements(DeduplicatedCollection[ArtifactRequirement]):
    """An ordered list of Coordinates used as requirements."""

    @classmethod
    def from_coordinates(cls, coordinates: Iterable[Coordinate]) -> ArtifactRequirements:
        return ArtifactRequirements(ArtifactRequirement(coord) for coord in coordinates)


@dataclass(frozen=True)
class GatherJvmCoordinatesRequest:
    """A request to turn strings of coordinates (`group:artifact:version`) and/or addresses to
    `jvm_artifact` targets into `ArtifactRequirements`."""

    artifact_inputs: FrozenOrderedSet[str]
    option_name: str
