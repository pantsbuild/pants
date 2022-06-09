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


class SkipBlackField(BoolField):
    alias = "skip_black"
    default = False
    help = "If true, don't run Black on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipBlackField),
        PythonSourceTarget.register_plugin_field(SkipBlackField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipBlackField),
        PythonTestTarget.register_plugin_field(SkipBlackField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipBlackField),
    ]
