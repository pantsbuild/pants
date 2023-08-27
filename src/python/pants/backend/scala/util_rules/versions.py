# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.engine.rules import collect_rules, rule
from pants.jvm.resolve.common import Coordinate


@dataclass(frozen=True)
class ScalaArtifactsForVersionRequest:
    scala_version: str


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
    version_parts = request.scala_version.split(".")
    if version_parts[0] == "3":
        return ScalaArtifactsForVersionResult(
            compiler_coordinate=Coordinate(
                group="org.scala-lang",
                artifact="scala3-compiler_3",
                version=request.scala_version,
            ),
            library_coordinate=Coordinate(
                group="org.scala-lang",
                artifact="scala3-library_3",
                version=request.scala_version,
            ),
            reflect_coordinate=None,
            compiler_main="dotty.tools.dotc.Main",
            repl_main="dotty.tools.repl.Main",
        )

    return ScalaArtifactsForVersionResult(
        compiler_coordinate=Coordinate(
            group="org.scala-lang",
            artifact="scala-compiler",
            version=request.scala_version,
        ),
        library_coordinate=Coordinate(
            group="org.scala-lang",
            artifact="scala-library",
            version=request.scala_version,
        ),
        reflect_coordinate=Coordinate(
            group="org.scala-lang",
            artifact="scala-reflect",
            version=request.scala_version,
        ),
        compiler_main="scala.tools.nsc.Main",
        repl_main="scala.tools.nsc.MainGenericRunner",
    )


def rules():
    return collect_rules()
