# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import (
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
)
from pants.engine.target import BoolField


class SkipMyPyField(BoolField):
    alias = "skip_mypy"
    default = False
    help = "If true, don't run MyPy on this target's code."


def rules():
    return [
        PythonSourceTarget.register_plugin_field(SkipMyPyField),
        PythonSourcesGeneratorTarget.register_plugin_field(SkipMyPyField),
        PythonTestTarget.register_plugin_field(SkipMyPyField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipMyPyField),
    ]
