# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.scala.compile import scalac
from pants.backend.scala.goals import check
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget, ScalaSourceTarget
from pants.backend.scala.target_types import rules as target_types_rules
from pants.jvm import classpath, jdk_rules
from pants.jvm import util_rules as jvm_util_rules
from pants.jvm.goals import coursier
from pants.jvm.resolve import coursier_fetch, coursier_setup
from pants.jvm.target_types import JvmArtifact, JvmDependencyLockfile


def target_types():
    return [
        ScalaSourceTarget,
        ScalaSourcesGeneratorTarget,
        JvmArtifact,
        JvmDependencyLockfile,
    ]


def rules():
    return [
        *check.rules(),
        *classpath.rules(),
        *coursier.rules(),
        *coursier_fetch.rules(),
        *coursier_setup.rules(),
        *jdk_rules.rules(),
        *jvm_util_rules.rules(),
        *scalac.rules(),
        *target_types_rules(),
    ]
