# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.scala.bench import scalameter
from pants.backend.scala.bsp.rules import rules as bsp_rules
from pants.backend.scala.compile import scalac
from pants.backend.scala.dependency_inference import rules as dep_inf_rules
from pants.backend.scala.goals import check, repl, tailor
from pants.backend.scala.resolve.lockfile import rules as scala_lockfile_rules
from pants.backend.scala.target_types import (
    ScalaArtifactTarget,
    ScalacPluginTarget,
    ScalaJunitTestsGeneratorTarget,
    ScalaJunitTestTarget,
    ScalameterBenchmarksGeneratorTarget,
    ScalameterBenchmarkTarget,
    ScalaSourceField,
    ScalaSourcesGeneratorTarget,
    ScalaSourceTarget,
    ScalatestTestsGeneratorTarget,
    ScalatestTestTarget,
)
from pants.backend.scala.target_types import build_file_aliases as scala_build_file_aliases
from pants.backend.scala.target_types import rules as target_types_rules
from pants.backend.scala.test import scalatest
from pants.core.util_rules.wrap_source import wrap_source_rule_and_target
from pants.jvm import jvm_common

wrap_scala = wrap_source_rule_and_target(ScalaSourceField, "scala_sources")


def target_types():
    return [
        ScalaJunitTestTarget,
        ScalaJunitTestsGeneratorTarget,
        ScalaSourceTarget,
        ScalaSourcesGeneratorTarget,
        ScalacPluginTarget,
        ScalatestTestTarget,
        ScalatestTestsGeneratorTarget,
        ScalaArtifactTarget,
        ScalameterBenchmarkTarget,
        ScalameterBenchmarksGeneratorTarget,
        *jvm_common.target_types(),
        *wrap_scala.target_types,
    ]


def rules():
    return [
        *scalac.rules(),
        *scalatest.rules(),
        *scalameter.rules(),
        *check.rules(),
        *tailor.rules(),
        *repl.rules(),
        *dep_inf_rules.rules(),
        *target_types_rules(),
        *scala_lockfile_rules(),
        *bsp_rules(),
        *jvm_common.rules(),
        *wrap_scala.rules,
    ]


def build_file_aliases():
    return jvm_common.build_file_aliases().merge(scala_build_file_aliases())
