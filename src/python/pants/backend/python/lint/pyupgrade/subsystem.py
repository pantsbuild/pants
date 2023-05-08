# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.subsystems.python_tool_base import (
    ExportToolOption,
    LockfileRules,
    PythonToolBase,
)
from pants.backend.python.target_types import ConsoleScript
from pants.backend.python.util_rules.export import ExportRules
from pants.engine.rules import collect_rules
from pants.option.option_types import ArgsListOption, SkipOption


class PyUpgrade(PythonToolBase):
    options_scope = "pyupgrade"
    name = "pyupgrade"
    help = (
        "Upgrade syntax for newer versions of the language (https://github.com/asottile/pyupgrade)."
    )

    default_version = "pyupgrade>=2.33.0,<4"
    default_main = ConsoleScript("pyupgrade")
    default_requirements = [default_version]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.pyupgrade", "pyupgrade.lock")
    lockfile_rules_type = LockfileRules.SIMPLE
    export_rules_type = ExportRules.NO_ICS

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--py39-plus --keep-runtime-typing")
    export = ExportToolOption()


def rules():
    return collect_rules()
