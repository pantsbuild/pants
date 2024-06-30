# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Iterable

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import Rule, collect_rules
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption
from pants.util.strutil import help_text


class ClangFormat(PythonToolBase):
    options_scope = "clang-format"
    name = "ClangFormat"
    help_short = help_text(
        """
        The clang-format utility for formatting C/C++ (and others) code
        (https://clang.llvm.org/docs/ClangFormat.html). The clang-format binaries
        are retrieved from PyPi (https://pypi.org/project/clang-format/).
        """
    )

    default_main = ConsoleScript("clang-format")
    default_requirements = ["clang-format>=14.0.3,<16"]

    register_interpreter_constraints = True

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--version")

    default_lockfile_resource = ("pants.backend.cc.lint.clangformat", "clangformat.lock")

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        """clang-format will use the closest configuration file to the file currently being
        formatted, so add all of them."""
        config_files = (
            ".clang-format",
            "_clang-format",
        )
        check_existence = [os.path.join(d, file) for file in config_files for d in ("", *dirs)]
        return ConfigFilesRequest(
            discovery=True,
            check_existence=check_existence,
        )


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        UnionRule(ExportableTool, ClangFormat),
    ]
