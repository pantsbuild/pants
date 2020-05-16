# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import COMMON_PYTHON_FIELDS, PythonSources
from pants.engine.target import Target


class PylintPluginSources(PythonSources):
    required = True
    expected_file_extensions = (".py",)


class PylintSourcePlugin(Target):
    """A Pylint plugin loaded through source code.

    To load a source plugin:

        1. Write your plugin. See http://pylint.pycqa.org/en/latest/how_tos/plugins.html.
        2. Define a `pylint_source_plugin` with the plugin's Python files included in the
            `sources` field.
        3. Set up a `pylintrc` config file, with these two values defined:
            a. `load-plugins=$module_name`. For example, if your Python file is called
                `pylint_plugin.py`, set `load-plugins=pylint_plugin`.
            b. `init-hook="import pathlib, sys; sys.path.append(pathlib.Path.cwd() / '$source_root_stripped_path')".
                Replace `$source_root_stripped_path` with the path to your plugin's parent
                directory after its source root has been stripped (see
                https://pants.readme.io/docs/source-roots). For example, if your plugin is located
                at build-support/pytest/plugin.py, and you configure the source root
                `build-support`, then you would configure:

                    init-hook="import pathlib, sys; sys.path.append(pathlib.Path.cwd() / 'pytest')

                This step is necessary for Pylint to know how to find your plugin.

        4. Set the option `config` in the `[pytest]` scope to the path of your `pylintrc` (relative
            to the build root).
        5. Set the option `source_plugins` in the `[pytest]` scope to include this target's
            address, e.g. `source_plugins = ["build-support/pytest:plugin"]`.

    To instead load a third-party plugin, set the option `extra_requirements` in the `[pytest]`
    scope. See https://pants.readme.io/docs/python-linters-and-formatters.

    This target is treated similarly to a `python_library` target. For example, Python linters
    and formatters will run on this target. You can include other targets in the `dependencies`
    field, and you can include this target in other targets, such a `python_tests` target.

    You can define the `provides` field to release this plugin as a distribution
    (https://pants.readme.io/docs/python-setup-py-goal).
    """

    alias = "pylint_source_plugin"
    core_fields = (*COMMON_PYTHON_FIELDS, PylintPluginSources)
