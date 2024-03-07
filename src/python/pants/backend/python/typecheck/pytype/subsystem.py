# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.option.option_types import ArgsListOption, FileOption, SkipOption
from pants.util.strutil import help_text, softwrap


class Pytype(PythonToolBase):
    options_scope = "pytype"
    name = "Pytype"
    help = help_text(
        """
        The Pytype utility for typechecking Python code
        (https://github.com/google/pytype).
        """
    )

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<3.11"]

    default_main = ConsoleScript("pytype")
    default_requirements = ["pytype==2023.6.16"]
    default_version = "pytype@2023.6.16"

    default_lockfile_resource = ("pants.backend.python.typecheck.pytype", "pytype.lock")

    skip = SkipOption("check")
    args = ArgsListOption(example="--version")
    config = FileOption(
        default=None,
        help=softwrap(
            """
            Path to an toml config file understood by Pytype
            (https://github.com/google/pytype#config-file).
            """
        ),
    )

    def config_request(self) -> ConfigFilesRequest:
        """Pytype will look for a  `pyproject.toml` (with a `[tool.pytype]` section) in the project
        root.

        Pytype's configuration content is specified here: https://github.com/google/pytype#config-
        file.
        """

        return ConfigFilesRequest(
            discovery=True,
            check_existence=[self.config] if self.config else [],
            check_content={"pyproject.toml": b"[tool.pytype"},
        )
