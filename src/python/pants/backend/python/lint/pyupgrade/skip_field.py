# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import (
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
)
from pants.engine.target import BoolField


class SkipPyUpgradeField(BoolField):
    alias = "skip_pyupgrade"
    default = False
    help = "If true, don't run pyupgrade on this target's code."


def rules():
    return [
        PythonSourceTarget.register_plugin_field(SkipPyUpgradeField),
        PythonSourcesGeneratorTarget.register_plugin_field(SkipPyUpgradeField),
        PythonTestTarget.register_plugin_field(SkipPyUpgradeField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipPyUpgradeField),
    ]
