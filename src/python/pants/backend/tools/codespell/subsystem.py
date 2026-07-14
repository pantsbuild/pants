# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.resolves import ExportableTool
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


class Codespell(PythonToolBase):
    name = "Codespell"
    options_scope = "codespell"
    help_short = "A tool to find common misspellings in text files (https://github.com/codespell-project/codespell)"

    default_main = ConsoleScript("codespell")
    default_requirements = ["codespell>=2.2.6,<3", "tomli>=1.1.0; python_version < '3.11'"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.tools.codespell", "codespell.lock")

    skip = SkipOption("lint")

    args = ArgsListOption(example="--quiet-level=2 --ignore-words-list=word1,word2")

    config_file_name = StrOption(
        "--config-file-name",
        default=".codespellrc",
        advanced=True,
        help=softwrap(
            """
            Name of a config file understood by codespell
            (https://github.com/codespell-project/codespell#using-a-config-file).
            The plugin will search the ancestors of each directory in which files are found
            for a config file of this name.
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
        default=["**/*"],
        help="Glob patterns for files to check with codespell.",
    )

    file_glob_exclude = StrListOption(
        "--exclude",
        default=[],
        help=softwrap(
            """
            Glob patterns for files to exclude from codespell checks.

            Machine-generated files such as lockfiles are a common source of false
            positives, and are best excluded. Use the `.add` syntax to extend rather
            than replace this option, e.g.:

                [codespell]
                exclude.add = ["**/*.lock", "**/package-lock.json", "**/go.sum"]
            """
        ),
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        UnionRule(ExportableTool, Codespell),
    ]
