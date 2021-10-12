# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import (
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
)
from pants.engine.target import BoolField


class SkipIsortField(BoolField):
    alias = "skip_isort"
    default = False
    help = "If true, don't run isort on this target's code."


def rules():
    return [
        PythonSourceTarget.register_plugin_field(SkipIsortField),
        PythonSourcesGeneratorTarget.register_plugin_field(SkipIsortField),
        PythonTestTarget.register_plugin_field(SkipIsortField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipIsortField),
    ]
