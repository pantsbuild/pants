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


class SkipMyPyField(BoolField):
    alias = "skip_mypy"
    default = False
    help = "If true, don't run MyPy on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipMyPyField),
        PythonSourceTarget.register_plugin_field(SkipMyPyField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipMyPyField),
        PythonTestTarget.register_plugin_field(SkipMyPyField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipMyPyField),
    ]
