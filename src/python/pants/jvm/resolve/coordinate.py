# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import re
from dataclasses import dataclass

from pants.engine.collection import DeduplicatedCollection


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
