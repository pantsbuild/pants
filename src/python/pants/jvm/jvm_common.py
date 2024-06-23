# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.jvm import classpath, jdk_rules, resources, run, run_deploy_jar
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.dependency_inference import symbol_mapper
from pants.jvm.goals import lockfile
from pants.jvm.jar_tool import jar_tool
from pants.jvm.package import deploy_jar
from pants.jvm.package.war import rules as war_rules
from pants.jvm.resolve import coursier_fetch, jvm_tool
from pants.jvm.shading.rules import rules as shading_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import (
    DeployJarTarget,
    JvmArtifactsTargetGenerator,
    JvmArtifactTarget,
    JvmWarTarget,
)
from pants.jvm.target_types import build_file_aliases as jvm_build_file_aliases
from pants.jvm.test import junit


def target_types():
    return [
        DeployJarTarget,
        JvmArtifactTarget,
        JvmArtifactsTargetGenerator,
        JvmWarTarget,
    ]


def rules():
    return [
        *classpath.rules(),
        *junit.rules(),
        *strip_jar.rules(),
        *shading_rules(),
        *deploy_jar.rules(),
        *jar_tool.rules(),
        *lockfile.rules(),
        *coursier_fetch.rules(),
        *resources.rules(),
        *symbol_mapper.rules(),
        *jvm_util_rules.rules(),
        *jdk_rules.rules(),
        *jvm_tool.rules(),
        *run.rules(),
        *run_deploy_jar.rules(),
        *war_rules(),
    ]


def build_file_aliases():
    return jvm_build_file_aliases()
