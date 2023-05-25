# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import (
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.engine.target import BoolField


class SkipPydocstyleField(BoolField):
    alias = "skip_pydocstyle"
    default = False
    help = "If true, don't run pydocstyle on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipPydocstyleField),
        PythonSourceTarget.register_plugin_field(SkipPydocstyleField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipPydocstyleField),
        PythonTestTarget.register_plugin_field(SkipPydocstyleField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipPydocstyleField),
    ]
