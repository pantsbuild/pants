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


class SkipRuffCheckField(BoolField):
    alias = "skip_ruff_check"
    default = False
    help = "If true, don't run the ruff checker on this target's code."

    deprecated_alias = "skip_ruff"
    deprecated_alias_removal_version = "2.22.0.dev0"


class SkipRuffFormatField(BoolField):
    alias = "skip_ruff_format"
    default = False
    help = "If true, don't run the ruff formatter on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipRuffCheckField),
        PythonSourcesGeneratorTarget.register_plugin_field(SkipRuffFormatField),
        PythonSourceTarget.register_plugin_field(SkipRuffCheckField),
        PythonSourceTarget.register_plugin_field(SkipRuffFormatField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipRuffCheckField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipRuffFormatField),
        PythonTestTarget.register_plugin_field(SkipRuffCheckField),
        PythonTestTarget.register_plugin_field(SkipRuffFormatField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipRuffCheckField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipRuffFormatField),
    ]
