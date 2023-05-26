# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote_plus as url_quote_plus

from pants.engine.collection import DeduplicatedCollection
from pants.engine.target import Target
from pants.jvm.target_types import (
    JvmArtifactArtifactField,
    JvmArtifactExclusionsField,
    JvmArtifactFieldSet,
    JvmArtifactGroupField,
    JvmArtifactJarSourceField,
    JvmArtifactUrlField,
    JvmArtifactVersionField,
)
from pants.util.ordered_set import FrozenOrderedSet


class InvalidCoordinateString(Exception):
    """The coordinate string being passed is invalid or malformed."""

    def __init__(self, coords: str) -> None:
        super().__init__(f"Received invalid artifact coordinates: {coords}")


@dataclass(frozen=True, order=True)
class Coordinate:
    """A single Maven-style coordinate for a JVM dependency.

    Coursier uses at least two string serializations of coordinates:
    1. A format that is accepted by the Coursier CLI which uses trailing attributes to specify
       optional fields like `packaging`/`type`, `classifier`, `url`, etc. See `to_coord_arg_str`.
    2. A format in the JSON report, which uses token counts to specify optional fields. We
       additionally use this format in our own lockfile. See `to_coord_str` and `from_coord_str`.
    """

    REGEX = re.compile("([^: ]+):([^: ]+)(:([^: ]*)(:([^: ]+))?)?:([^: ]+)")

    group: str
    artifact: str
    version: str
    packaging: str = "jar"
    classifier: str | None = None

    # True to enforce that the exact declared version of a coordinate is fetched, rather than
    # allowing dependency resolution to adjust the version when conflicts occur.
    strict: bool = True

    @staticmethod
    def from_json_dict(data: dict) -> Coordinate:
        return Coordinate(
            group=data["group"],
            artifact=data["artifact"],
            version=data["version"],
            packaging=data.get("packaging", "jar"),
            classifier=data.get("classifier", None),
        )

    def to_json_dict(self) -> dict:
        ret = {
            "group": self.group,
            "artifact": self.artifact,
            "version": self.version,
            "packaging": self.packaging,
            "classifier": self.classifier,
        }
        return ret

    @classmethod
    def from_coord_str(cls, s: str) -> Coordinate:
        """Parses from a coordinate string with optional `packaging` and `classifier` coordinates.

        See the classdoc for more information on the format.

        Using Aether's implementation as reference
        http://www.javased.com/index.php?source_dir=aether-core/aether-api/src/main/java/org/eclipse/aether/artifact/DefaultArtifact.java

        ${organisation}:${artifact}[:${packaging}[:${classifier}]]:${version}

        See also: `to_coord_str`.
        """

        parts = Coordinate.REGEX.match(s)
        if parts is not None:
            packaging_part = parts.group(4)
            return cls(
                group=parts.group(1),
                artifact=parts.group(2),
                packaging=packaging_part if packaging_part is not None else "jar",
                classifier=parts.group(6),
                version=parts.group(7),
            )
        else:
            raise InvalidCoordinateString(s)

    def as_requirement(self) -> ArtifactRequirement:
        """Creates a `RequirementCoordinate` from a `Coordinate`."""
        return ArtifactRequirement(coordinate=self)

    def to_coord_str(self, versioned: bool = True) -> str:
        """Renders the coordinate in Coursier's JSON-report format, which does not use attributes.

        See also: `from_coord_str`.
        """
        unversioned = f"{self.group}:{self.artifact}"
        if self.classifier is not None:
            unversioned += f":{self.packaging}:{self.classifier}"
        elif self.packaging != "jar":
            unversioned += f":{self.packaging}"

        version_suffix = ""
        if versioned:
            version_suffix = f":{self.version}"
        return f"{unversioned}{version_suffix}"

    def to_coord_arg_str(self, extra_attrs: dict[str, str] | None = None) -> str:
        """Renders the coordinate in Coursier's CLI input format.

        The CLI input format uses trailing key-val attributes to specify `packaging`, `url`, etc.

        See https://github.com/coursier/coursier/blob/b5d5429a909426f4465a9599d25c678189a54549/modules/coursier/shared/src/test/scala/coursier/parse/DependencyParserTests.scala#L7
        """
        attrs = dict(extra_attrs or {})
        if self.packaging != "jar":
            # NB: Coursier refers to `packaging` as `type` internally.
            attrs["type"] = self.packaging
        if self.classifier:
            attrs["classifier"] = self.classifier
        attrs_sep_str = "," if attrs else ""
        attrs_str = ",".join((f"{k}={v}" for k, v in attrs.items()))
        return f"{self.group}:{self.artifact}:{self.version}{attrs_sep_str}{attrs_str}"


class Coordinates(DeduplicatedCollection[Coordinate]):
    """An ordered list of `Coordinate`s."""


@dataclass(frozen=True)
class ArtifactRequirement:
    """A single Maven-style coordinate for a JVM dependency, along with information of how to fetch
    the dependency if it is not to be fetched from a Maven repository."""

    coordinate: Coordinate

    url: str | None = None
    jar: JvmArtifactJarSourceField | None = None
    excludes: frozenset[str] | None = None

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
        return ArtifactRequirements(coord.as_requirement() for coord in coordinates)


@dataclass(frozen=True)
class GatherJvmCoordinatesRequest:
    """A request to turn strings of coordinates (`group:artifact:version`) and/or addresses to
    `jvm_artifact` targets into `ArtifactRequirements`."""

    artifact_inputs: FrozenOrderedSet[str]
    option_name: str
