# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.scala.dependency_inference.symbol_mapper import AllScalaTargets
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.goals.lockfile import (
    ValidatedJvmArtifactsForResolve,
    ValidateJvmArtifactsForResolveRequest,
)
from pants.jvm.subsystems import JvmSubsystem

SCALA_LIBRARY_GROUP = "org.scala-lang"
SCALA_LIBRARY_ARTIFACT = "scala-library"


class ValidateResolveHasScalaRuntimeRequest(ValidateJvmArtifactsForResolveRequest):
    pass


@rule
async def validate_scala_runtime_is_present_in_resolve(
    request: ValidateResolveHasScalaRuntimeRequest,
    scala_subsystem: ScalaSubsystem,
    scala_targets: AllScalaTargets,
    jvm: JvmSubsystem,
) -> ValidatedJvmArtifactsForResolve:
    first_party_target_uses_this_resolve = False
    for tgt in scala_targets:
        tgt_resolve_name = jvm.resolve_for_target(tgt)
        if tgt_resolve_name == request.resolve_name:
            first_party_target_uses_this_resolve = True
            break

    if not first_party_target_uses_this_resolve:
        return ValidatedJvmArtifactsForResolve()

    scala_version = scala_subsystem.version_for_resolve(request.resolve_name)

    has_scala_library_artifact = False
    for artifact in request.artifacts:
        if (
            artifact.coordinate.group == SCALA_LIBRARY_GROUP
            and artifact.coordinate.artifact == SCALA_LIBRARY_ARTIFACT
        ):
            if artifact.coordinate.version != scala_version:
                raise ValueError(
                    f"The JVM resolve `{request.resolve_name}` contains a `jvm_artifact` for version {artifact.coordinate.version} "
                    f"of the Scala runtime. This conflicts with Scala version {scala_version} which is the configured version "
                    "of Scala for this resolve from the `[scala].version_for_resolve` option. "
                    "Please remove the `jvm_artifact` target with JVM coordinate "
                    f"{artifact.coordinate.to_coord_str()}, then re-run the `generate-lockfiles` goal."
                )

            # This does not `break` so the loop can validate the entire set of requirements to ensure no conflicting
            # scala-library requirement.
            has_scala_library_artifact = True

    if not has_scala_library_artifact:
        raise ValueError(
            f"The JVM resolve `{request.resolve_name}` does not contain a requirement for the Scala runtime. "
            "Since at least one Scala target type in this repository consumes this resolve, the resolve "
            "must contain a `jvm_artifact` target for the Scala runtime.\n\n"
            "Please add the following `jvm_artifact` target somewhere in the repository and re-run "
            "the `generate-lockfiles` goal:\n"
            "jvm_artifact(\n"
            f'  name="{SCALA_LIBRARY_GROUP}_{SCALA_LIBRARY_ARTIFACT}_{scala_version}",\n'
            f'  group="{SCALA_LIBRARY_GROUP}",\n',
            f'  artifact="{SCALA_LIBRARY_ARTIFACT}",\n',
            f'  version="{scala_version}",\n',
            f'  resolve="{request.resolve_name}",\n',
            ")",
        )

    return ValidatedJvmArtifactsForResolve()


def rules():
    return (
        *collect_rules(),
        UnionRule(ValidateJvmArtifactsForResolveRequest, ValidateResolveHasScalaRuntimeRequest),
    )
