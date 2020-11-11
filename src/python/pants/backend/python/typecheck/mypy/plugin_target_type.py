# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import COMMON_PYTHON_FIELDS, PythonSources
from pants.engine.target import Dependencies, Target


class MyPyPluginSources(PythonSources):
    required = True


class MyPySourcePlugin(Target):
    """A MyPy plugin loaded through source code.

    To load a source plugin:

        1. Write your plugin. See https://mypy.readthedocs.io/en/stable/extending_mypy.html.
        2. Define a `mypy_source_plugin` target with the plugin's Python file(s) included in the
            `sources` field.
        3. Add `plugins = path.to.module` to your MyPy config file, using the name of the module
            without source roots. For example, if your Python file is called
            `pants-plugins/mypy_plugins/custom_plugin.py`, and you set `pants-plugins` as a source root,
            then set `plugins = mypy_plugins.custom_plugin`. Set the `config`
            option in the `[mypy]` scope to point to your MyPy config file.
        4. Set the option `source_plugins` in the `[mypy]` scope to include this target's
            address, e.g. `source_plugins = ["pants-plugins/mypy_plugins:plugin"]`.

    To instead load a third-party plugin, set the option `extra_requirements` in the `[mypy]`
    scope (see https://www.pantsbuild.org/v2.0/docs/python-typecheck-goal). Set `plugins` in
    your config file, like you'd do with a source plugin.

    This target type is treated similarly to a `python_library` target. For example, Python linters
    and formatters will run on this target.

    You can depend on other targets and Pants's dependency inference will add them to the `dependencies` field,
    including any third-party requirements and `python_library` targets (even if their source files live in a different
    directory).

    Other targets can depend on this target. This allows you to write a `python_tests` target for
    this code or a `python_distribution` target to distribute the plugin externally.
    """

    alias = "mypy_source_plugin"
    core_fields = (*COMMON_PYTHON_FIELDS, Dependencies, MyPyPluginSources)
