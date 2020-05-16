# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import PythonSources
from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Target


class PylintPluginSources(PythonSources):
    expected_file_extensions = (".py",)


class PylintSourcePlugin(Target):
    """A custom Pylint plugin...

    This is treated similarly to a `python_library` target. For example, Python linters and
    formatters will run on this target
.
    See ...
    """

    alias = "pylint_source_plugin"
    # TODO: make this more like a `python_library`.
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, PylintPluginSources)
