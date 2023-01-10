# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.option.option_types import ArgsListOption, SkipOption, StrListOption, StrOption
from pants.util.strutil import softwrap


class Yamllint(PythonToolBase):
    name = "Yamllint"
    options_scope = "yamllint"
    help = "A linter for YAML files (https://yamllint.readthedocs.io)"

    default_version = "yamllint==1.28.0"
    default_main = ConsoleScript("yamllint")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6,<4"]

    config_file_name = StrOption(
        "--config-file-glob",
        default=".yamllint",
        advanced=True,
        help=lambda cls: softwrap(
            """
            Name of a config file understood by yamllint (https://yamllint.readthedocs.io/en/stable/configuration.html).
            The plugin will search the ancestors of each directory in which YAML files are found for a config file of this name.
            """
        ),
    )

    file_glob_include = StrListOption(
        "--include",
        default=["**/*.yml", "**/*.yaml"],
        help=lambda cls: softwrap(
            """
                Glob for which YAML files to lint.
                """
        ),
    )

    file_glob_exclude = StrListOption(
        "--exclude",
        default=[],
        help=lambda cls: softwrap(
            """
                Glob for which YAML files to exclude from linting.
                """
        ),
    )

    args = ArgsListOption(example="-d relaxed")

    skip = SkipOption("lint")
