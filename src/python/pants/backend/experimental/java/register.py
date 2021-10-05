# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.java import classpath, tailor
from pants.backend.java.compile import javac
from pants.backend.java.dependency_inference import (
    import_parser,
    java_parser,
    java_parser_launcher,
    package_mapper,
)
from pants.backend.java.dependency_inference import rules as dependency_inference_rules
from pants.backend.java.package import deploy_jar
from pants.backend.java.target_types import (
    DeployJar,
    JavaSourcesGeneratorTarget,
    JavaSourceTarget,
    JunitTestsGeneratorTarget,
    JunitTestTarget,
)
from pants.backend.java.target_types import rules as target_types_rules
from pants.backend.java.test import junit
from pants.jvm import jdk_rules
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.goals import coursier
from pants.jvm.resolve import coursier_fetch, coursier_setup
from pants.jvm.target_types import JvmArtifact, JvmDependencyLockfile


def target_types():
    return [
        DeployJar,
        JavaSourceTarget,
        JavaSourcesGeneratorTarget,
        JunitTestTarget,
        JunitTestsGeneratorTarget,
        JvmArtifact,
        JvmDependencyLockfile,
    ]


def rules():
    return [
        *javac.rules(),
        *junit.rules(),
        *classpath.rules(),
        *deploy_jar.rules(),
        *coursier.rules(),
        *coursier_fetch.rules(),
        *coursier_setup.rules(),
        *import_parser.rules(),
        *java_parser.rules(),
        *java_parser_launcher.rules(),
        *package_mapper.rules(),
        *dependency_inference_rules.rules(),
        *tailor.rules(),
        *jvm_util_rules.rules(),
        *jdk_rules.rules(),
        *target_types_rules(),
    ]
