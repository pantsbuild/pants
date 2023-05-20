# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.target_types import (
    ScalaArtifactExclusionRule,
    ScalaArtifactFieldSet,
    ScalaArtifactTarget,
)
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import GeneratedTargets, GenerateTargetsRequest
from pants.engine.unions import UnionMembership, UnionRule
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import (
    JvmArtifactArtifactField,
    JvmArtifactExcludeDependenciesField,
    JvmArtifactExclusionRule,
    JvmArtifactTarget,
)


class GenerateJvmArtifactForScalaTargets(GenerateTargetsRequest):
    generate_from = ScalaArtifactTarget


@rule
async def generate_jvm_artifact_targets(
    request: GenerateJvmArtifactForScalaTargets,
    jvm: JvmSubsystem,
    scala: ScalaSubsystem,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    field_set = ScalaArtifactFieldSet.create(request.generator)
    scala_version = scala.version_for_resolve(field_set.resolve.normalized_value(jvm))
    scala_version_parts = scala_version.split(".")

    def scala_suffix(full_crossversion: bool) -> str:
        if full_crossversion:
            return scala_version
        elif int(scala_version_parts[0]) >= 3:
            return scala_version_parts[0]

        return f"{scala_version_parts[0]}.{scala_version_parts[1]}"

    exclude_dependencies_field = {}
    if field_set.excludes.value:
        exclusion_rules = []
        for exclusion_rule in field_set.excludes.value:
            if not isinstance(exclusion_rule, ScalaArtifactExclusionRule):
                exclusion_rules.append(exclusion_rule)
            else:
                excluded_artifact_name = None
                if exclusion_rule.artifact:
                    excluded_artifact_name = f"{exclusion_rule.artifact}_{scala_suffix(exclusion_rule.full_crossversion)}"
                exclusion_rules.append(
                    JvmArtifactExclusionRule(
                        group=exclusion_rule.group, artifact=excluded_artifact_name
                    )
                )
        exclude_dependencies_field[JvmArtifactExcludeDependenciesField.alias] = exclusion_rules

    artifact_name = f"{field_set.artifact.value}_{scala_suffix(field_set.full_crossversion.value)}"
    jvm_artifact_target = JvmArtifactTarget(
        {
            **request.template,
            JvmArtifactArtifactField.alias: artifact_name,
            **exclude_dependencies_field,
        },
        request.generator.address.create_generated(artifact_name),
        union_membership,
        residence_dir=request.generator.address.spec_path,
    )

    return GeneratedTargets(request.generator, (jvm_artifact_target,))


def rules() -> list[Rule | UnionRule]:
    return [*collect_rules(), UnionRule(GenerateTargetsRequest, GenerateJvmArtifactForScalaTargets)]
