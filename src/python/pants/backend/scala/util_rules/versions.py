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
    compiler_main: str


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
            compiler_main="dotty.tools.dotc.Main",
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
        compiler_main="scala.tools.nsc.Main",
    )


def rules():
    return collect_rules()
