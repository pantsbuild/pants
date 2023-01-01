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


class SkipPylintField(BoolField):
    alias = "skip_pylint"
    default = False
    help = "If true, don't run Pylint on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipPylintField),
        PythonSourceTarget.register_plugin_field(SkipPylintField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipPylintField),
        PythonTestTarget.register_plugin_field(SkipPylintField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipPylintField),
    ]
