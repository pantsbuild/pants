# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import InterpreterConstraintsField, PythonSources
from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Target
from pants.util.docutil import docs_url


class PylintPluginSources(PythonSources):
    required = True


class PylintPluginDependencies(Dependencies):
    help = (
        "Addresses to other targets that this plugin depends on.\n\nDue to restrictions with "
        "Pylint plugins, these targets must either be third-party Python dependencies "
        f"({docs_url('python-third-party-dependencies')}) or be located within "
        "this target's same directory or a subdirectory."
    )


class PylintSourcePlugin(Target):
    alias = "pylint_source_plugin"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        InterpreterConstraintsField,
        PylintPluginDependencies,
        PylintPluginSources,
    )
    help = (
        "A Pylint plugin loaded through source code.\n\nRun `./pants help-advanced pylint` for "
        "instructions with the `--source-plugins` option."
    )

    deprecated_removal_version = "2.3.0.dev0"
    deprecated_removal_hint = (
        "Use a `python_library` target rather than `pylint_source_plugin`, which behaves "
        "identically. If you change the target's name, update `[pylint].source_plugins`."
    )
