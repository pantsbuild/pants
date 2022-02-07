# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.java.compile import javac
from pants.backend.java.dependency_inference import java_parser, java_parser_launcher
from pants.backend.java.dependency_inference import rules as dependency_inference_rules
from pants.backend.java.goals import check, tailor
from pants.backend.java.target_types import (
    JavaSourcesGeneratorTarget,
    JavaSourceTarget,
    JunitTestsGeneratorTarget,
    JunitTestTarget,
)
from pants.backend.java.target_types import rules as target_types_rules
from pants.jvm import classpath, jdk_rules, resources, run_deploy_jar
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.dependency_inference import symbol_mapper
from pants.jvm.goals import lockfile
from pants.jvm.package import deploy_jar
from pants.jvm.resolve import coursier_fetch, jvm_tool
from pants.jvm.target_types import DeployJarTarget, JvmArtifactTarget
from pants.jvm.test import junit


def target_types():
    return [
        DeployJarTarget,
        JavaSourceTarget,
        JavaSourcesGeneratorTarget,
        JunitTestTarget,
        JunitTestsGeneratorTarget,
        JvmArtifactTarget,
    ]


def rules():
    return [
        *javac.rules(),
        *check.rules(),
        *classpath.rules(),
        *junit.rules(),
        *deploy_jar.rules(),
        *lockfile.rules(),
        *coursier_fetch.rules(),
        *java_parser.rules(),
        *java_parser_launcher.rules(),
        *resources.rules(),
        *symbol_mapper.rules(),
        *dependency_inference_rules.rules(),
        *tailor.rules(),
        *jvm_util_rules.rules(),
        *jdk_rules.rules(),
        *target_types_rules(),
        *jvm_tool.rules(),
        *run_deploy_jar.rules(),
    ]
