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


class SkipAddTrailingCommaField(BoolField):
    alias = "skip_add_trailing_comma"
    default = False
    help = "If true, don't run add-trailing-comma on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipAddTrailingCommaField),
        PythonSourceTarget.register_plugin_field(SkipAddTrailingCommaField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipAddTrailingCommaField),
        PythonTestTarget.register_plugin_field(SkipAddTrailingCommaField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipAddTrailingCommaField),
    ]
