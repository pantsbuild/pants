# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolBase
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.option.option_types import ArgsListOption, SkipOption, StrListOption
from pants.util.strutil import help_text


class Pyright(NodeJSToolBase):
    options_scope = "pyright"
    name = "Pyright"
    help = help_text(
        """
        The Pyright utility for typechecking Python code
        (https://github.com/microsoft/pyright).
        """
    )

    default_version = "pyright@1.1.365"

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

    def config_request(self) -> ConfigFilesRequest:
        """Pyright will look for a `pyrightconfig.json` or a `pyproject.toml` (with a
        `[tool.pyright]` section) in the project root.

        `pyrightconfig.json` takes precedence if both are present.
        Pyright's configuration content is specified here:
        https://github.com/microsoft/pyright/blob/main/docs/configuration.md.

        In order for Pants to work with Pyright, we modify the config file before
        putting it in the Pyright digest. Specifically, we append source roots
        to `extraPaths` and we overwrite `venv` to point to a pex venv.
        """

        return ConfigFilesRequest(
            discovery=True,
            check_existence=["pyrightconfig.json"],
            check_content={"pyproject.toml": b"[tool.pyright"},
        )
