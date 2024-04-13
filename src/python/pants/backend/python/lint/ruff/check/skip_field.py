# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.python.target_types import (
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.engine.target import BoolField


class SkipRuffCheckField(BoolField):
    alias = "skip_ruff_check"
    default = False
    help = "If true, don't run the ruff checker on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipRuffCheckField),
        PythonSourceTarget.register_plugin_field(SkipRuffCheckField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipRuffCheckField),
        PythonTestTarget.register_plugin_field(SkipRuffCheckField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipRuffCheckField),
    ]
