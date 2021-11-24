# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import (
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.engine.target import BoolField


class SkipAutoflakeField(BoolField):
    alias = "skip_autoflake"
    default = False
    help = "If true, don't run Autoflake on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipAutoflakeField),
        PythonSourceTarget.register_plugin_field(SkipAutoflakeField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipAutoflakeField),
        PythonTestTarget.register_plugin_field(SkipAutoflakeField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipAutoflakeField),
    ]
