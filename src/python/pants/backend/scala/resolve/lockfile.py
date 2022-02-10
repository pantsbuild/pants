# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.scala.dependency_inference.symbol_mapper import AllScalaTargets
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.goals.lockfile import (
    AugmentedJvmArtifactsForResolve,
    AugmentJvmArtifactsForResolveRequest,
)
from pants.jvm.resolve.common import ArtifactRequirement, ArtifactRequirements, Coordinate
from pants.jvm.subsystems import JvmSubsystem

_SCALA_LIBRARY_GROUP = "org.scala-lang"
_SCALA_LIBRARY_ARTIFACT = "scala-library"


class AugmentResolveWithScalaArtifactsRequest(AugmentJvmArtifactsForResolveRequest):
    pass


@rule
async def propose_scala_artifacts_for_resolve(
    request: AugmentResolveWithScalaArtifactsRequest,
    scala_subsystem: ScalaSubsystem,
    scala_targets: AllScalaTargets,
    jvm: JvmSubsystem,
) -> AugmentedJvmArtifactsForResolve:
    first_party_target_uses_this_resolve = False
    for tgt in scala_targets:
        resolves_for_target = jvm.resolves_for_target(tgt)
        if request.resolve_name in resolves_for_target:
            first_party_target_uses_this_resolve = True
            break

    if not first_party_target_uses_this_resolve:
        return AugmentedJvmArtifactsForResolve(None)

    scala_version = scala_subsystem.version_for_resolve(request.resolve_name)
    # TODO: Uncomment this once `--scala-version` goes away in v2.11.x.
    # if scala_version is None:
    #     raise ValueError(
    #         f"Resolve `{request.resolve_name}` is used by at least one Scala target, but no Scala version "
    #         "for the resolve was set in the `[scala].version_for_resolve` option. Please set the "
    #         "Scala version to use in the `[scala].version_for_resolve` option."
    #     )

    has_scala_library_artifact = False
    for artifact in request.artifacts:
        if (
            artifact.coordinate.group == _SCALA_LIBRARY_GROUP
            and artifact.coordinate.artifact == _SCALA_LIBRARY_ARTIFACT
        ):
            has_scala_library_artifact = True

    if not has_scala_library_artifact:
        artifacts = ArtifactRequirements(
            [
                ArtifactRequirement(
                    coordinate=Coordinate(
                        group=_SCALA_LIBRARY_GROUP,
                        artifact=_SCALA_LIBRARY_ARTIFACT,
                        version=scala_version,
                    )
                ),
            ]
        )
        return AugmentedJvmArtifactsForResolve(artifacts)
    else:
        return AugmentedJvmArtifactsForResolve(None)


def rules():
    return (
        *collect_rules(),
        UnionRule(AugmentJvmArtifactsForResolveRequest, AugmentResolveWithScalaArtifactsRequest),
    )
