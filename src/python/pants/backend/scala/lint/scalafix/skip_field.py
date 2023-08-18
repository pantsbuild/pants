# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget, ScalaSourceTarget
from pants.engine.target import BoolField


class SkipScalafixField(BoolField):
    alias = "skip_scalafix"
    default = False
    help = "If true, don't run `scalafix` on this target's code."


def rules():
    return [
        ScalaSourceTarget.register_plugin_field(SkipScalafixField),
        ScalaSourcesGeneratorTarget.register_plugin_field(SkipScalafixField),
    ]
