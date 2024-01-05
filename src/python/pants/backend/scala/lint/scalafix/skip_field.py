# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.scala.target_types import (
    ScalaJunitTestsGeneratorTarget,
    ScalaJunitTestTarget,
    ScalaSourcesGeneratorTarget,
    ScalaSourceTarget,
    ScalatestTestsGeneratorTarget,
    ScalatestTestTarget,
)
from pants.engine.target import BoolField, Target


class SkipScalafixField(BoolField):
    alias = "skip_scalafix"
    default = False
    help = "If true, don't run `scalafix` on this target's code."


_SCALA_TARGET_TYPES: list[type[Target]] = [
    ScalaSourceTarget,
    ScalaSourcesGeneratorTarget,
    ScalatestTestTarget,
    ScalatestTestsGeneratorTarget,
    ScalaJunitTestTarget,
    ScalaJunitTestsGeneratorTarget,
]


def rules():
    return [tgt.register_plugin_field(SkipScalafixField) for tgt in _SCALA_TARGET_TYPES]
