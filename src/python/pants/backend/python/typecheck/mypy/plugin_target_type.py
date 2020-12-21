# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import InterpreterConstraintsField, PythonSources
from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Target


class MyPyPluginSources(PythonSources):
    required = True


class MyPySourcePlugin(Target):
    alias = "mypy_source_plugin"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        InterpreterConstraintsField,
        Dependencies,
        MyPyPluginSources,
    )
    help = (
        "A MyPy plugin loaded through source code.\n\nRun `./pants help-advanced mypy` for "
        "instructions with the `--source-plugins` option."
    )

    deprecated_removal_version = "2.3.0.dev0"
    deprecated_removal_hint = (
        "Use a `python_library` target rather than `mypy_source_plugin`, which behaves "
        "identically. If you change the target's name, update `[mypy].source_plugins`."
    )
