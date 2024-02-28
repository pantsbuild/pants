# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.python.target_types import PythonSourceTarget, PythonSourcesGeneratorTarget, PythonTestTarget, PythonTestUtilsGeneratorTarget, PythonTestsGeneratorTarget
from pants.engine.target import BoolField


class SkipRuffFormatField(BoolField):
    alias = "skip_ruff_format"
    default = False
    help = "If true, don't run the ruff formatter on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipRuffFormatField),
        PythonSourceTarget.register_plugin_field(SkipRuffFormatField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipRuffFormatField),
        PythonTestTarget.register_plugin_field(SkipRuffFormatField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipRuffFormatField),
    ]