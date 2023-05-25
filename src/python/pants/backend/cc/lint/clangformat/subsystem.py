# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Iterable

from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.subsystems.python_tool_base import (
    ExportToolOption,
    LockfileRules,
    PythonToolBase,
)
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption
from pants.util.strutil import help_text


class ClangFormat(PythonToolBase):
    options_scope = "clang-format"
    name = "ClangFormat"
    help = help_text(
        """
        The clang-format utility for formatting C/C++ (and others) code
        (https://clang.llvm.org/docs/ClangFormat.html). The clang-format binaries
        are retrieved from PyPi (https://pypi.org/project/clang-format/).
        """
    )

    default_version = "clang-format>=14.0.3,<16"
    default_main = ConsoleScript("clang-format")
    default_requirements = [default_version]

    register_interpreter_constraints = True

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--version")

    default_lockfile_resource = ("pants.backend.cc.lint.clangformat", "clangformat.lock")
    lockfile_rules_type = LockfileRules.SIMPLE

    export = ExportToolOption()

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


class ClangFormatExportSentinel(ExportPythonToolSentinel):
    pass


@rule
def clangformat_export(_: ClangFormatExportSentinel, clangformat: ClangFormat) -> ExportPythonTool:
    if not clangformat.export:
        return ExportPythonTool(resolve_name=clangformat.options_scope, pex_request=None)
    return ExportPythonTool(
        resolve_name=clangformat.options_scope, pex_request=clangformat.to_pex_request()
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(ExportPythonToolSentinel, ClangFormatExportSentinel),
    )
