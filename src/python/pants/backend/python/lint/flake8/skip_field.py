# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import (
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
)
from pants.engine.target import BoolField


class SkipFlake8Field(BoolField):
    alias = "skip_flake8"
    default = False
    help = "If true, don't run Flake8 on this target's code."


def rules():
    return [
        PythonSourceTarget.register_plugin_field(SkipFlake8Field),
        PythonSourcesGeneratorTarget.register_plugin_field(SkipFlake8Field),
        PythonTestTarget.register_plugin_field(SkipFlake8Field),
        PythonTestsGeneratorTarget.register_plugin_field(SkipFlake8Field),
    ]
