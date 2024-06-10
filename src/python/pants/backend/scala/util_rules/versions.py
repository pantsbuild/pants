# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pants.engine.rules import collect_rules, rule
from pants.jvm.resolve.coordinate import Coordinate
from pants.util.strutil import softwrap


class InvalidScalaVersion(ValueError):
    def __init__(self, scala_version: str) -> None:
        super().__init__(
            softwrap(
                f"""Value '{scala_version}' is not a valid Scala version.
            It should be formed of [major].[minor].[patch]"""
            )
        )


class ScalaCrossVersionMode(Enum):
    BINARY = "binary"
    FULL = "full"


_SCALA_VERSION_PATTERN = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)(\-(.+))?$")


@dataclass(frozen=True)
class ScalaVersion:
    major: int
    minor: int
    patch: int
    suffix: str | None = None

    @classmethod
    def parse(cls, scala_version: str) -> ScalaVersion:
        matched = _SCALA_VERSION_PATTERN.match(scala_version)
        if not matched:
            raise InvalidScalaVersion(scala_version)

        return cls(
            major=int(matched.groups()[0]),
            minor=int(matched.groups()[1]),
            patch=int(matched.groups()[2]),
            suffix=matched.groups()[4] if len(matched.groups()) == 5 else None,
        )

    def crossversion(self, mode: ScalaCrossVersionMode) -> str:
        if mode == ScalaCrossVersionMode.FULL:
            return str(self)
        if self.major >= 3:
            return str(self.major)
        return f"{self.major}.{self.minor}"

    @property
    def binary(self) -> str:
        return self.crossversion(ScalaCrossVersionMode.BINARY)

    def __eq__(self, other: Any) -> bool:
        return (
            isinstance(other, ScalaVersion)
            and other.major == self.major
            and other.minor == self.minor
            and other.patch == self.patch
            and other.suffix == self.suffix
        )

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, ScalaVersion):
            if self.major > other.major:
                return True
            elif (self.major == other.major) and (self.minor > other.minor):
                return True
            elif (self.major == other.major) and (self.minor == other.minor):
                return self.patch > other.patch
            return False
        return False

    def __str__(self) -> str:
        version_str = f"{self.major}.{self.minor}.{self.patch}"
        if self.suffix:
            version_str += f"-{self.suffix}"
        return version_str


@dataclass(frozen=True)
class ScalaArtifactsForVersionRequest:
    scala_version: ScalaVersion


@dataclass(frozen=True)
class ScalaArtifactsForVersionResult:
    compiler_coordinate: Coordinate
    library_coordinate: Coordinate
    reflect_coordinate: Coordinate | None
    compiler_main: str
    repl_main: str

    @property
    def all_coordinates(self) -> tuple[Coordinate, ...]:
        coords = [self.compiler_coordinate, self.library_coordinate]
        if self.reflect_coordinate:
            coords.append(self.reflect_coordinate)
        return tuple(coords)


@rule
async def resolve_scala_artifacts_for_version(
    request: ScalaArtifactsForVersionRequest,
) -> ScalaArtifactsForVersionResult:
    if request.scala_version.major == 3:
        return ScalaArtifactsForVersionResult(
            compiler_coordinate=Coordinate(
                group="org.scala-lang",
                artifact="scala3-compiler_3",
                version=str(request.scala_version),
            ),
            library_coordinate=Coordinate(
                group="org.scala-lang",
                artifact="scala3-library_3",
                version=str(request.scala_version),
            ),
            reflect_coordinate=None,
            compiler_main="dotty.tools.dotc.Main",
            repl_main="dotty.tools.repl.Main",
        )

    return ScalaArtifactsForVersionResult(
        compiler_coordinate=Coordinate(
            group="org.scala-lang",
            artifact="scala-compiler",
            version=str(request.scala_version),
        ),
        library_coordinate=Coordinate(
            group="org.scala-lang",
            artifact="scala-library",
            version=str(request.scala_version),
        ),
        reflect_coordinate=Coordinate(
            group="org.scala-lang",
            artifact="scala-reflect",
            version=str(request.scala_version),
        ),
        compiler_main="scala.tools.nsc.Main",
        repl_main="scala.tools.nsc.MainGenericRunner",
    )


def rules():
    return collect_rules()
