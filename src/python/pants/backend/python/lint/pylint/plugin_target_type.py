# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import COMMON_PYTHON_FIELDS, PythonSources
from pants.engine.target import Dependencies, Target
from pants.util.ordered_set import FrozenOrderedSet


class PylintPluginSources(PythonSources):
    required = True
    expected_file_extensions = (".py",)


# NB: We solely subclass this to change the docstring.
class PylintPluginDependencies(Dependencies):
    """Addresses to other targets that this plugin depends on.

    Due to restrictions with Pylint plugins, these targets must either be third-party Python
    dependencies (https://pants.readme.io/docs/python-third-party-dependencies) or be located
    within this target's same directory or a subdirectory.
    """


class PylintSourcePlugin(Target):
    """A Pylint plugin loaded through source code.

    To load a source plugin:

        1. Write your plugin. See http://pylint.pycqa.org/en/latest/how_tos/plugins.html.
        2. Define a `pylint_source_plugin` target with the plugin's Python files included in the
            `sources` field.
        3. Add the parent directory of your target to the `root_patterns` option in the `[source]`
            scope. For example, if your plugin is at `build-support/pylint/custom_plugin.py`, add
            'build-support/pylint'. This is necessary for Pants to know how to tell Pylint to
            discover your plugin. See https://pants.readme.io/docs/source-roots.
        4. Add `load-plugins=$module_name` to your Pylint config file. For example, if your Python
            file is called `custom_plugin.py`, set `load-plugins=custom_plugin`. Set the `config`
            option in the `[pylint]` scope to point to your Pylint config file.
        5. Set the option `source_plugins` in the `[pylint]` scope to include this target's
            address, e.g. `source_plugins = ["build-support/pylint:plugin"]`.

    To instead load a third-party plugin, set the option `extra_requirements` in the `[pylint]`
    scope (see https://pants.readme.io/docs/python-linters-and-formatters). Set `load-plugins` in
    your config file, like you'd do with a source plugin.

    This target type is treated similarly to a `python_library` target. For example, Python linters
    and formatters will run on this target.

    You can include other targets in the `dependencies` field, so long as those targets are
    third-party dependencies or are located in the same directory or a subdirectory.

    Other targets can depend on this target. This allows you to write a `python_tests` target for
    this code.

    You can define the `provides` field to release this plugin as a distribution
    (https://pants.readme.io/docs/python-setup-py-goal).
    """

    alias = "pylint_source_plugin"
    core_fields = (
        *(FrozenOrderedSet(COMMON_PYTHON_FIELDS) - {Dependencies}),  # type: ignore[misc]
        PylintPluginDependencies,
        PylintPluginSources,
    )
