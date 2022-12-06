# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.javascript.subsystems.npx_tool import NpxToolBase
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.option.option_types import ArgsListOption, SkipOption, StrListOption
from pants.util.strutil import softwrap


class Pyright(NpxToolBase):
    options_scope = "pyright"
    name = "Pyright"
    help = softwrap(
        """
        The Pyright utility for typechecking Python code
        (https://github.com/microsoft/pyright).
        """
    )

    default_version = "pyright@1.1.274"

    skip = SkipOption("check")
    args = ArgsListOption(example="--version")

    _interpreter_constraints = StrListOption(
        advanced=True,
        default=["CPython>=3.7,<4"],
        help="Python interpreter constraints for Pyright (which is, itself, a NodeJS tool).",
    )

    @property
    def interpreter_constraints(self) -> InterpreterConstraints:
        """The interpreter constraints to use when installing and running the tool.

        This assumes you have set the class property `register_interpreter_constraints = True`.
        """
        return InterpreterConstraints(self._interpreter_constraints)
