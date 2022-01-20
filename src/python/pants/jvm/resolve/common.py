# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote_plus as url_quote_plus

import toml

from pants.base import deprecated
from pants.engine.collection import DeduplicatedCollection
from pants.engine.fs import Digest, FileDigest
from pants.engine.target import Target
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.jvm.target_types import (
    JvmArtifactArtifactField,
    JvmArtifactFieldSet,
    JvmArtifactGroupField,
    JvmArtifactJarSourceField,
    JvmArtifactTarget,
    JvmArtifactUrlField,
    JvmArtifactVersionField,
)


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


@dataclass(frozen=True, order=True)
class ArtifactRequirement:
    """A single Maven-style coordinate for a JVM dependency, along with information of how to fetch
    the dependency if it is not to be fetched from a Maven repository."""

    coordinate: Coordinate

    url: str | None = None
    jar: JvmArtifactJarSourceField | None = None

    @classmethod
    def from_jvm_artifact_target(cls, target: Target) -> ArtifactRequirement:
        if not JvmArtifactFieldSet.is_applicable(target):
            raise AssertionError(
                "`ArtifactRequirement.from_jvm_artifact_target()` only works on targets with "
                "`JvmArtifactFieldSet` fields present."
            )
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
        )

    def to_coord_arg_str(self) -> str:
        return self.coordinate.to_coord_arg_str(
            {"url": url_quote_plus(self.url)} if self.url else {}
        )

    def to_metadata_str(self) -> str:
        return self.coordinate.to_coord_arg_str(
            {
                "url": self.url or "not_provided",
                "jar": self.jar.address.spec if self.jar else "not_provided",
            }
        )


# TODO: Consider whether to carry classpath scope in some fashion via ArtifactRequirements.
class ArtifactRequirements(DeduplicatedCollection[ArtifactRequirement]):
    """An ordered list of Coordinates used as requirements."""

    @classmethod
    def from_coordinates(cls, coordinates: Iterable[Coordinate]) -> ArtifactRequirements:
        return ArtifactRequirements(coord.as_requirement() for coord in coordinates)


class CoursierError(Exception):
    """An exception relating to invoking Coursier or processing its output."""


@dataclass(frozen=True)
class CoursierLockfileEntry:
    """A single artifact entry from a Coursier-resolved lockfile.

    These fields are nearly identical to the JSON objects from the
    "dependencies" entries in Coursier's --json-output-file format.
    But unlike Coursier's JSON report, a CoursierLockfileEntry
    includes the content-address of the artifact fetched by Coursier
    and ingested by Pants.

    For example, a Coursier JSON report dependency entry might look like this:

    ```
    {
      "coord": "com.chuusai:shapeless_2.13:2.3.3",
      "file": "/home/USER/.cache/coursier/v1/https/repo1.maven.org/maven2/com/chuusai/shapeless_2.13/2.3.3/shapeless_2.13-2.3.3.jar",
      "directDependencies": [
        "org.scala-lang:scala-library:2.13.0"
      ],
      "dependencies": [
        "org.scala-lang:scala-library:2.13.0"
      ]
    }
    ```

    The equivalent CoursierLockfileEntry would look like this:

    ```
    CoursierLockfileEntry(
        coord="com.chuusai:shapeless_2.13:2.3.3", # identical
        file_name="shapeless_2.13-2.3.3.jar" # PurePath(entry["file"].name)
        direct_dependencies=(Coordinate.from_coord_str("org.scala-lang:scala-library:2.13.0"),),
        dependencies=(Coordinate.from_coord_str("org.scala-lang:scala-library:2.13.0"),),
        file_digest=FileDigest(fingerprint=<sha256 of the jar>, ...),
    )
    ```

    The fields `remote_url` and `pants_address` are set by Pants if the `coord` field matches a
    `jvm_artifact` that had either the `url` or `jar` fields set.
    """

    coord: Coordinate
    file_name: str
    direct_dependencies: Coordinates
    dependencies: Coordinates
    file_digest: FileDigest
    remote_url: str | None = None
    pants_address: str | None = None

    @classmethod
    def from_json_dict(cls, entry) -> CoursierLockfileEntry:
        """Construct a CoursierLockfileEntry from its JSON dictionary representation."""

        return cls(
            coord=Coordinate.from_json_dict(entry["coord"]),
            file_name=entry["file_name"],
            direct_dependencies=Coordinates(
                Coordinate.from_json_dict(d) for d in entry["directDependencies"]
            ),
            dependencies=Coordinates(Coordinate.from_json_dict(d) for d in entry["dependencies"]),
            file_digest=FileDigest(
                fingerprint=entry["file_digest"]["fingerprint"],
                serialized_bytes_length=entry["file_digest"]["serialized_bytes_length"],
            ),
            remote_url=entry.get("remote_url"),
            pants_address=entry.get("pants_address"),
        )

    def to_json_dict(self) -> dict[str, Any]:
        """Export this CoursierLockfileEntry to a JSON object."""

        return dict(
            coord=self.coord.to_json_dict(),
            directDependencies=[coord.to_json_dict() for coord in self.direct_dependencies],
            dependencies=[coord.to_json_dict() for coord in self.dependencies],
            file_name=self.file_name,
            file_digest=dict(
                fingerprint=self.file_digest.fingerprint,
                serialized_bytes_length=self.file_digest.serialized_bytes_length,
            ),
            remote_url=self.remote_url,
            pants_address=self.pants_address,
        )


@dataclass(frozen=True)
class CoursierResolvedLockfile:
    """An in-memory representation of Pants' Coursier lockfile format.

    All coordinates in the resolved lockfile will be compatible, so we do not need to do version
    testing when looking up coordinates.
    """

    entries: tuple[CoursierLockfileEntry, ...]
    metadata: JVMLockfileMetadata | None = None

    @classmethod
    def _coordinate_not_found(cls, key: CoursierResolveKey, coord: Coordinate) -> CoursierError:
        # TODO: After fixing https://github.com/pantsbuild/pants/issues/13496, coordinate matches
        # should become exact, and this error message will capture all cases of stale lockfiles.
        return CoursierError(
            f"{coord} was not present in resolve `{key.name}` at `{key.path}`.\n"
            f"If you have recently added new `{JvmArtifactTarget.alias}` targets, you might "
            f"need to update your lockfile by running `coursier-resolve --names={key.name}`."
        )

    def direct_dependencies(
        self, key: CoursierResolveKey, coord: Coordinate
    ) -> tuple[CoursierLockfileEntry, tuple[CoursierLockfileEntry, ...]]:
        """Return the entry for the given Coordinate, and for its direct dependencies."""
        entries = {(i.coord.group, i.coord.artifact): i for i in self.entries}
        entry = entries.get((coord.group, coord.artifact))
        if entry is None:
            raise self._coordinate_not_found(key, coord)

        return (entry, tuple(entries[(i.group, i.artifact)] for i in entry.direct_dependencies))

    def dependencies(
        self, key: CoursierResolveKey, coord: Coordinate
    ) -> tuple[CoursierLockfileEntry, tuple[CoursierLockfileEntry, ...]]:
        """Return the entry for the given Coordinate, and for its transitive dependencies."""
        entries = {(i.coord.group, i.coord.artifact): i for i in self.entries}
        entry = entries.get((coord.group, coord.artifact))
        if entry is None:
            raise self._coordinate_not_found(key, coord)

        return (entry, tuple(entries[(i.group, i.artifact)] for i in entry.dependencies))

    @classmethod
    def from_json_dicts(cls, json_lock_entries) -> CoursierResolvedLockfile:
        """Construct a CoursierResolvedLockfile from its JSON dictionary representation."""

        return cls(
            entries=tuple(CoursierLockfileEntry.from_json_dict(dep) for dep in json_lock_entries)
        )

    @classmethod
    def from_toml(cls, lockfile: str | bytes) -> CoursierResolvedLockfile:
        """Constructs a CoursierResolvedLockfile from it's TOML + metadata comment representation.

        The toml file should consist of an `[entries]` block, followed by several entries.
        """

        lockfile_str: str
        lockfile_bytes: bytes
        if isinstance(lockfile, str):
            lockfile_str = lockfile
            lockfile_bytes = lockfile.encode("utf-8")
        else:
            lockfile_str = lockfile.decode("utf-8")
            lockfile_bytes = lockfile

        contents = toml.loads(lockfile_str)
        entries = tuple(
            CoursierLockfileEntry.from_json_dict(entry) for entry in (contents["entries"])
        )
        metadata = JVMLockfileMetadata.from_lockfile(lockfile_bytes)

        return cls(
            entries=entries,
            metadata=metadata,
        )

    @classmethod
    def from_serialized(cls, lockfile: str | bytes) -> CoursierResolvedLockfile:
        """Construct a CoursierResolvedLockfile from its serialized representation (either TOML with
        attached metadata, or old-style JSON.)."""

        try:
            return cls.from_toml(lockfile)
        except toml.TomlDecodeError:
            deprecated.warn_or_error(
                "2.11.0.dev0",
                "JSON-encoded JVM lockfile",
                "Run `./pants generate-lockfiles` to generate lockfiles in the new format.",
            )
            return cls.from_json_dicts(json.loads(lockfile))

    def to_serialized(self) -> bytes:
        """Export this CoursierResolvedLockfile to a human-readable serialized form.

        This serialized form is intended to be checked in to the user's repo as a hermetic snapshot
        of a Coursier resolved JVM classpath.
        """

        lockfile = {
            "entries": [entry.to_json_dict() for entry in self.entries],
        }

        return toml.dumps(lockfile).encode("utf-8")


@dataclass(frozen=True)
class CoursierResolveKey:
    name: str
    path: str
    digest: Digest
