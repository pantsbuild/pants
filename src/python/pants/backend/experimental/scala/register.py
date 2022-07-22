# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.scala.bsp.rules import rules as bsp_rules
from pants.backend.scala.compile import scalac
from pants.backend.scala.dependency_inference import rules as dep_inf_rules
from pants.backend.scala.goals import check, repl, tailor
from pants.backend.scala.resolve.lockfile import rules as scala_lockfile_rules
from pants.backend.scala.target_types import (
    ScalacPluginTarget,
    ScalaJunitTestsGeneratorTarget,
    ScalaJunitTestTarget,
    ScalaSourcesGeneratorTarget,
    ScalaSourceTarget,
    ScalatestTestsGeneratorTarget,
    ScalatestTestTarget,
)
from pants.backend.scala.target_types import rules as target_types_rules
from pants.backend.scala.test import scalatest
from pants.jvm import classpath, jdk_rules, resources, run_deploy_jar
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.goals import lockfile
from pants.jvm.package import deploy_jar
from pants.jvm.package.war import rules as war_rules
from pants.jvm.resolve import coursier_fetch, coursier_setup, jvm_tool
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import DeployJarTarget, JvmArtifactTarget, JvmWarTarget
from pants.jvm.test import junit


def target_types():
    return [
        DeployJarTarget,
        JvmArtifactTarget,
        JvmWarTarget,
        ScalaJunitTestTarget,
        ScalaJunitTestsGeneratorTarget,
        ScalaSourceTarget,
        ScalaSourcesGeneratorTarget,
        ScalacPluginTarget,
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
        *strip_jar.rules(),
        *deploy_jar.rules(),
        *lockfile.rules(),
        *coursier_fetch.rules(),
        *coursier_setup.rules(),
        *jvm_util_rules.rules(),
        *jdk_rules.rules(),
        *dep_inf_rules.rules(),
        *target_types_rules(),
        *jvm_tool.rules(),
        *resources.rules(),
        *run_deploy_jar.rules(),
        *scala_lockfile_rules(),
        *bsp_rules(),
        *war_rules(),
    ]
