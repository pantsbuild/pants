# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.scala.dependency_inference.symbol_mapper import AllScalaTargets
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.util_rules.versions import (
    ScalaArtifactsForVersionRequest,
    ScalaArtifactsForVersionResult,
)
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.goals.lockfile import (
    ValidateJvmArtifactsForResolveRequest,
    ValidateJvmArtifactsForResolveResult,
)
from pants.jvm.resolve.common import Coordinate
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.docutil import bin_name

SCALA_LIBRARY_GROUP = "org.scala-lang"
SCALA_LIBRARY_ARTIFACT = "scala-library"
SCALA3_LIBRARY_ARTIFACT = "scala3-library_3"


class ConflictingScalaLibraryVersionInResolveError(ValueError):
    """Exception for when there is a conflicting Scala version in a resolve."""

    def __init__(
        self, resolve_name: str, required_version: str, conflicting_coordinate: Coordinate
    ) -> None:
        super().__init__(
            f"The JVM resolve `{resolve_name}` contains a `jvm_artifact` for version {conflicting_coordinate.version} "
            f"of the Scala runtime. This conflicts with Scala version {required_version} which is the configured version "
            "of Scala for this resolve from the `[scala].version_for_resolve` option. "
            "Please remove the `jvm_artifact` target with JVM coordinate "
            f"{conflicting_coordinate.to_coord_str()}, then re-run "
            f"`{bin_name()} generate-lockfiles --resolve={resolve_name}`"
        )


class MissingScalaLibraryInResolveError(ValueError):
    def __init__(self, resolve_name: str, scala_library_coordinate: Coordinate) -> None:
        super().__init__(
            f"The JVM resolve `{resolve_name}` does not contain a requirement for the Scala runtime. "
            "Since at least one Scala target type in this repository consumes this resolve, the resolve "
            "must contain a `jvm_artifact` target for the Scala runtime.\n\n"
            "Please add the following `jvm_artifact` target somewhere in the repository and re-run "
            f"`{bin_name()} generate-lockfiles --resolve={resolve_name}`:\n"
            "jvm_artifact(\n"
            f'  name="{scala_library_coordinate.group}_{scala_library_coordinate.artifact}_{scala_library_coordinate.version}",\n'
            f'  group="{scala_library_coordinate.group}",\n',
            f'  artifact="{scala_library_coordinate.artifact}",\n',
            f'  version="{scala_library_coordinate.version}",\n',
            f'  resolve="{resolve_name}",\n',
            ")",
        )


class ValidateResolveHasScalaRuntimeRequest(ValidateJvmArtifactsForResolveRequest):
    pass


@rule
async def validate_scala_runtime_is_present_in_resolve(
    request: ValidateResolveHasScalaRuntimeRequest,
    scala_subsystem: ScalaSubsystem,
    scala_targets: AllScalaTargets,
    jvm: JvmSubsystem,
) -> ValidateJvmArtifactsForResolveResult:
    first_party_target_uses_this_resolve = False
    for tgt in scala_targets:
        if tgt[JvmResolveField].normalized_value(jvm) == request.resolve_name:
            first_party_target_uses_this_resolve = True
            break

    if not first_party_target_uses_this_resolve:
        return ValidateJvmArtifactsForResolveResult()

    scala_version = scala_subsystem.version_for_resolve(request.resolve_name)
    scala_artifacts = await Get(
        ScalaArtifactsForVersionResult, ScalaArtifactsForVersionRequest(scala_version)
    )

    has_scala_library_artifact = False
    for artifact in request.artifacts:
        if (
            artifact.coordinate.group == SCALA_LIBRARY_GROUP
            and artifact.coordinate.artifact == scala_artifacts.library_coordinate.artifact
        ):
            if artifact.coordinate.version != str(scala_version):
                raise ConflictingScalaLibraryVersionInResolveError(
                    request.resolve_name, str(scala_version), artifact.coordinate
                )

            # This does not `break` so the loop can validate the entire set of requirements to ensure no conflicting
            # scala-library requirement.
            has_scala_library_artifact = True

    if not has_scala_library_artifact:
        raise MissingScalaLibraryInResolveError(
            request.resolve_name, scala_artifacts.library_coordinate
        )

    return ValidateJvmArtifactsForResolveResult()


def rules():
    return (
        *collect_rules(),
        UnionRule(ValidateJvmArtifactsForResolveRequest, ValidateResolveHasScalaRuntimeRequest),
    )
