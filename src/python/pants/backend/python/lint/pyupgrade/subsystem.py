# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules
from pants.option.option_types import ArgsListOption, SkipOption


class PyUpgrade(PythonToolBase):
    options_scope = "pyupgrade"
    name = "pyupgrade"
    help_short = (
        "Upgrade syntax for newer versions of the language (https://github.com/asottile/pyupgrade)."
    )

    default_main = ConsoleScript("pyupgrade")
    default_requirements = ["pyupgrade>=2.33.0,<4"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.pyupgrade", "pyupgrade.lock")

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--py39-plus --keep-runtime-typing")


def rules():
    return collect_rules()
