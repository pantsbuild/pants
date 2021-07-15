# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import PythonLibrary, PythonTests
from pants.engine.target import BoolField


class SkipYapfField(BoolField):
    alias = "skip_yapf"
    default = False
    help = "If true, don't run yapf on this target's code."


def rules():
    return [
        PythonLibrary.register_plugin_field(SkipYapfField),
        PythonTests.register_plugin_field(SkipYapfField),
    ]
