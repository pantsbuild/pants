# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget, ScalaSourceTarget
from pants.engine.target import BoolField


class SkipScalafmtField(BoolField):
    alias = "skip_scalafmt"
    default = False
    help = "If true, don't run `scalafmt` on this target's code."


def rules():
    return [
        ScalaSourceTarget.register_plugin_field(SkipScalafmtField),
        ScalaSourcesGeneratorTarget.register_plugin_field(SkipScalafmtField),
    ]
