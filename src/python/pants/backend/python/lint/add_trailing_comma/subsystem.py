# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules
from pants.option.option_types import ArgsListOption, SkipOption


class AddTrailingComma(PythonToolBase):
    options_scope = "add-trailing-comma"
    name = "add-trailing-comma"
    help = "The add-trailing-comma Python code formatter (https://github.com/asottile/add-trailing-comma)."

    default_main = ConsoleScript("add-trailing-comma")
    default_requirements = ["add-trailing-comma>=2.2.3,<3"]

    register_interpreter_constraints = True

    default_lockfile_resource = (
        "pants.backend.python.lint.add_trailing_comma",
        "add_trailing_comma.lock",
    )

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--py36-plus")


def rules():
    return collect_rules()
