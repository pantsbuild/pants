# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.java.package import deploy_jar  # TODO: Should move to the JVM package.
from pants.backend.java.target_types import DeployJarTarget  # TODO: Should move to the JVM package.
from pants.backend.scala.compile import scalac
from pants.backend.scala.dependency_inference import rules as dep_inf_rules
from pants.backend.scala.goals import check, repl, tailor
from pants.backend.scala.target_types import (
    ScalaJunitTestsGeneratorTarget,
    ScalaJunitTestTarget,
    ScalaSourcesGeneratorTarget,
    ScalaSourceTarget,
    ScalatestTestsGeneratorTarget,
    ScalatestTestTarget,
)
from pants.backend.scala.target_types import rules as target_types_rules
from pants.backend.scala.test import scalatest
from pants.jvm import classpath, jdk_rules
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.goals import coursier
from pants.jvm.resolve import coursier_fetch, coursier_setup, jvm_tool
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.test import junit


def target_types():
    return [
        DeployJarTarget,
        JvmArtifactTarget,
        ScalaJunitTestTarget,
        ScalaJunitTestsGeneratorTarget,
        ScalaSourceTarget,
        ScalaSourcesGeneratorTarget,
        ScalatestTestTarget,
        ScalatestTestsGeneratorTarget,
    ]


def rules():
    return [
        *scalac.rules(),
        *scalatest.rules(),
        *check.rules(),
        *tailor.rules(),
        *repl.rules(),
        *classpath.rules(),
        *junit.rules(),
        *deploy_jar.rules(),
        *coursier.rules(),
        *coursier_fetch.rules(),
        *coursier_setup.rules(),
        *jvm_util_rules.rules(),
        *jdk_rules.rules(),
        *dep_inf_rules.rules(),
        *target_types_rules(),
        *jvm_tool.rules(),
    ]
