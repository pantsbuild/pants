# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.goals import lockfile
from pants.backend.python.lint.bandit.skip_field import SkipBanditField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonSourceField,
)
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules
from pants.engine.target import FieldSet, Target
from pants.option.option_types import ArgsListOption, FileOption, SkipOption


@dataclass(frozen=True)
class BanditFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipBanditField).value


class Bandit(PythonToolBase):
    options_scope = "bandit"
    name = "Bandit"
    help = "A tool for finding security issues in Python code (https://bandit.readthedocs.io)."

    default_main = ConsoleScript("bandit")
    default_requirements = [
        "bandit>=1.7.0,<1.8",
        # When upgrading, check if Bandit has started using PEP 517 (a `pyproject.toml` file).
        # If so, remove `setuptools` here.
        "setuptools",
        # GitPython 3.1.20 was yanked because it breaks Python 3.8+, but Poetry's lockfile
        # generation still tries to use it.
        "GitPython>=3.1.24",
    ]

    default_lockfile_resource = ("pants.backend.python.lint.bandit", "bandit.lock")

    skip = SkipOption("lint")
    args = ArgsListOption(example="--skip B101,B308 --confidence")
    config = FileOption(
        default=None,
        advanced=True,
        help="Path to a Bandit YAML config file (https://bandit.readthedocs.io/en/latest/config.html).",
    )

    @property
    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://bandit.readthedocs.io/en/latest/config.html. Note that there are no
        # default locations for Bandit config files.
        return ConfigFilesRequest(
            specified=self.config, specified_option_name=f"{self.options_scope}.config"
        )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
    )
