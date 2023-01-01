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


class SkipDocformatterField(BoolField):
    alias = "skip_docformatter"
    default = False
    help = "If true, don't run Docformatter on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipDocformatterField),
        PythonSourceTarget.register_plugin_field(SkipDocformatterField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipDocformatterField),
        PythonTestTarget.register_plugin_field(SkipDocformatterField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipDocformatterField),
    ]
