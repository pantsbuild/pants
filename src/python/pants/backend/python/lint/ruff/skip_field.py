# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import (
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.engine.target import BoolField


class SkipRuffField(BoolField):
    alias = "skip_ruff"
    default = False
    help = "If true, don't run ruff on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipRuffField),
        PythonSourceTarget.register_plugin_field(SkipRuffField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipRuffField),
        PythonTestTarget.register_plugin_field(SkipRuffField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipRuffField),
    ]
