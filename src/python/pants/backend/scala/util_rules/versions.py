# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pants.base.deprecated import warn_or_error
from pants.engine.rules import collect_rules, rule
from pants.jvm.resolve.common import Coordinate
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
    PARTIAL = "partial"
    BINARY = "binary"
    FULL = "full"

    @classmethod
    def from_str(cls, value: str) -> ScalaCrossVersionMode:
        if value == ScalaCrossVersionMode.PARTIAL.value:
            warn_or_error(
                "2.21.0",
                f"Scala cross version: {value}",
                "Use value `binary` instead",
                start_version="2.20.0",
            )
        return cls(value)


@dataclass(frozen=True)
class ScalaVersion:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, scala_version: str) -> ScalaVersion:
        version_parts = scala_version.split(".")
        if len(version_parts) != 3:
            raise InvalidScalaVersion(scala_version)
        return cls(
            major=int(version_parts[0]), minor=int(version_parts[1]), patch=int(version_parts[2])
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

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


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
