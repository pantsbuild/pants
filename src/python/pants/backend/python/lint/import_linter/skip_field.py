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


class SkipImportLinterField(BoolField):
    alias = "skip_importlinter"
    default = False
    help = "If true, don't run Import Linter on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipImportLinterField),
        PythonSourceTarget.register_plugin_field(SkipImportLinterField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipImportLinterField),
        PythonTestTarget.register_plugin_field(SkipImportLinterField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipImportLinterField),
    ]
