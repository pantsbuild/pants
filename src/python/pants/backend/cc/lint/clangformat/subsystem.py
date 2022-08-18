# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Iterable

from pants.backend.python.goals import lockfile
from pants.backend.python.helpers import metalint
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import Rule, collect_rules
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption
from pants.util.docutil import git_url
from pants.util.strutil import softwrap


class ClangFormat(PythonToolBase):
    options_scope = "clang-format"
    name = "ClangFormat"
    help = softwrap(
        """
        The clang-format utility for formatting C/C++ (and others) code
        (https://clang.llvm.org/docs/ClangFormat.html). The clang-format binaries
        are retrieved from PyPi (https://pypi.org/project/clang-format/).
        """
    )

    default_version = "clang-format==14.0.3"
    default_main = ConsoleScript("clang-format")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--version")

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.cc.lint.clangformat", "clangformat.lock")
    default_lockfile_path = "src/python/pants/backend/cc/lint/clangformat/clangformat.lock"
    default_lockfile_url = git_url(default_lockfile_path)

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


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *lockfile.rules(),
        *metalint.make_export_rules(ClangFormat),
        *metalint.make_lockfile_rules(ClangFormat),
    )
