# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.java.bsp import rules as java_bsp_rules
from pants.backend.java.compile import javac
from pants.backend.java.dependency_inference import java_parser
from pants.backend.java.dependency_inference import rules as dependency_inference_rules
from pants.backend.java.goals import check, tailor
from pants.backend.java.target_types import (
    JavaSourcesGeneratorTarget,
    JavaSourceTarget,
    JunitTestsGeneratorTarget,
    JunitTestTarget,
)
from pants.backend.java.target_types import rules as target_types_rules
from pants.core.util_rules import archive
from pants.jvm import classpath, jdk_rules, resources, run_deploy_jar
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.dependency_inference import symbol_mapper
from pants.jvm.goals import lockfile
from pants.jvm.package import deploy_jar
from pants.jvm.package.war import rules as war_rules
from pants.jvm.resolve import coursier_fetch, jvm_tool
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import DeployJarTarget, JvmArtifactTarget, JvmWarTarget
from pants.jvm.test import junit


def target_types():
    return [
        DeployJarTarget,
        JavaSourceTarget,
        JavaSourcesGeneratorTarget,
        JunitTestTarget,
        JunitTestsGeneratorTarget,
        JvmArtifactTarget,
        JvmWarTarget,
    ]


def rules():
    return [
        *javac.rules(),
        *check.rules(),
        *classpath.rules(),
        *junit.rules(),
        *strip_jar.rules(),
        *deploy_jar.rules(),
        *lockfile.rules(),
        *coursier_fetch.rules(),
        *java_parser.rules(),
        *resources.rules(),
        *symbol_mapper.rules(),
        *dependency_inference_rules.rules(),
        *tailor.rules(),
        *jvm_util_rules.rules(),
        *jdk_rules.rules(),
        *target_types_rules(),
        *jvm_tool.rules(),
        *run_deploy_jar.rules(),
        *war_rules(),
        *java_bsp_rules.rules(),
        *archive.rules(),
    ]
