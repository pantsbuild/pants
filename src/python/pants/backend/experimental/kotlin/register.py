# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.kotlin.compile import kotlinc, kotlinc_plugins
from pants.backend.kotlin.dependency_inference.rules import rules as dep_inf_rules
from pants.backend.kotlin.goals import check, tailor
from pants.backend.kotlin.target_types import (
    KotlincPluginTarget,
    KotlinJunitTestsGeneratorTarget,
    KotlinJunitTestTarget,
    KotlinSourcesGeneratorTarget,
    KotlinSourceTarget,
)
from pants.backend.kotlin.target_types import rules as target_types_rules
from pants.backend.kotlin.test.junit import rules as kotlin_junit_rules
from pants.core.util_rules import source_files, system_binaries
from pants.jvm import classpath, jdk_rules, resources, run_deploy_jar
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.goals import lockfile
from pants.jvm.jar_tool import jar_tool
from pants.jvm.package import deploy_jar, war
from pants.jvm.resolve import coursier_fetch, coursier_setup, jvm_tool
from pants.jvm.shading.rules import rules as shading_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import DeployJarTarget, JvmArtifactTarget, JvmWarTarget
from pants.jvm.target_types import build_file_aliases as jvm_build_file_aliases
from pants.jvm.test.junit import rules as jvm_junit_rules


def target_types():
    return [
        JvmArtifactTarget,
        KotlinSourceTarget,
        KotlinSourcesGeneratorTarget,
        KotlincPluginTarget,
        KotlinJunitTestTarget,
        KotlinJunitTestsGeneratorTarget,
        DeployJarTarget,
        JvmWarTarget,
    ]


def rules():
    return [
        *kotlinc.rules(),
        *kotlinc_plugins.rules(),
        *check.rules(),
        *tailor.rules(),
        *classpath.rules(),
        *lockfile.rules(),
        *coursier_fetch.rules(),
        *coursier_setup.rules(),
        *shading_rules(),
        *dep_inf_rules(),
        *jvm_util_rules.rules(),
        *jdk_rules.rules(),
        *target_types_rules(),
        *jvm_tool.rules(),
        *resources.rules(),
        *system_binaries.rules(),
        *source_files.rules(),
        *strip_jar.rules(),
        *deploy_jar.rules(),
        *jar_tool.rules(),
        *run_deploy_jar.rules(),
        *war.rules(),
        *jvm_junit_rules(),
        *kotlin_junit_rules(),
    ]


def build_file_aliases():
    return jvm_build_file_aliases()
