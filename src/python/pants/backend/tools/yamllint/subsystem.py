# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import OrphanFilepathConfigBehavior
from pants.engine.rules import Rule, collect_rules
from pants.engine.unions import UnionRule
from pants.option.option_types import (
    ArgsListOption,
    EnumOption,
    SkipOption,
    StrListOption,
    StrOption,
)
from pants.util.strutil import softwrap


class Yamllint(PythonToolBase):
    name = "Yamllint"
    options_scope = "yamllint"
    help_short = "A linter for YAML files (https://yamllint.readthedocs.io)"

    default_main = ConsoleScript("yamllint")
    default_requirements = ["yamllint>=1.28.0,<2"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.tools.yamllint", "yamllint.lock")

    config_file_name = StrOption(
        "--config-file-name",
        default=".yamllint",
        advanced=True,
        help=softwrap(
            """
            Name of a config file understood by yamllint (https://yamllint.readthedocs.io/en/stable/configuration.html).
            The plugin will search the ancestors of each directory in which YAML files are found for a config file of this name.
            """
        ),
    )

    orphan_files_behavior = EnumOption(
        default=OrphanFilepathConfigBehavior.IGNORE,
        advanced=True,
        help=softwrap(
            f"""
            Whether to ignore, error or show a warning when files are found that are not
            covered by the config file provided in `[{options_scope}].config_file_name` setting.
            """
        ),
    )

    file_glob_include = StrListOption(
        "--include",
        default=["**/*.yml", "**/*.yaml"],
        help="Glob for which YAML files to lint.",
    )

    file_glob_exclude = StrListOption(
        "--exclude",
        default=[],
        help="Glob for which YAML files to exclude from linting.",
    )

    args = ArgsListOption(example="-d relaxed")

    skip = SkipOption("lint")


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
