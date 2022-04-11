# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.kotlin.compile import kotlinc
from pants.backend.kotlin.dependency_inference.rules import rules as dep_inf_rules
from pants.backend.kotlin.goals import check, tailor
from pants.backend.kotlin.target_types import KotlinSourcesGeneratorTarget, KotlinSourceTarget
from pants.backend.kotlin.target_types import rules as target_types_rules
from pants.core.util_rules import source_files, system_binaries
from pants.jvm import classpath, jdk_rules, resources, run_deploy_jar
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.package.war import rules as war_rules
from pants.jvm.resolve import coursier_fetch, coursier_setup, jvm_tool
from pants.jvm.target_types import DeployJarTarget, JvmArtifactTarget, JvmWarTarget


def target_types():
    return [
        DeployJarTarget,
        JvmArtifactTarget,
        JvmWarTarget,
        KotlinSourceTarget,
        KotlinSourcesGeneratorTarget,
    ]


def rules():
    return [
        *kotlinc.rules(),
        *check.rules(),
        *tailor.rules(),
        *classpath.rules(),
        *coursier_fetch.rules(),
        *coursier_setup.rules(),
        *dep_inf_rules(),
        *jvm_util_rules.rules(),
        *jdk_rules.rules(),
        *target_types_rules(),
        *jvm_tool.rules(),
        *resources.rules(),
        *run_deploy_jar.rules(),
        *war_rules(),
        *system_binaries.rules(),
        *source_files.rules(),
    ]
