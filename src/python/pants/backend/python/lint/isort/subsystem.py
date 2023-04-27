# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable

from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.subsystems.python_tool_base import (
    ExportToolOption,
    LockfileRules,
    PythonToolBase,
)
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, BoolOption, FileListOption, SkipOption
from pants.util.strutil import softwrap


class Isort(PythonToolBase):
    options_scope = "isort"
    name = "isort"
    help = "The Python import sorter tool (https://pycqa.github.io/isort/)."

    default_version = "isort[pyproject,colors]>=5.9.3,<6.0"
    default_main = ConsoleScript("isort")
    default_requirements = [default_version]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.isort", "isort.lock")
    lockfile_rules_type = LockfileRules.SIMPLE

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--case-sensitive --trailing-comma")
    export = ExportToolOption()
    config = FileListOption(
        # TODO: Figure out how to deprecate this being a list in favor of a single string.
        #  Thanks to config autodiscovery, this option should only be used because you want
        #  Pants to explicitly set `--settings`, which only works w/ 1 config file.
        #  isort 4 users should instead use autodiscovery to support multiple config files.
        #  Deprecating this could be tricky, but should be possible thanks to the implicit
        #  add syntax.
        #
        #  When deprecating, also deprecate the user manually setting `--settings` with
        #  `[isort].args`.
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to config file understood by isort
            (https://pycqa.github.io/isort/docs/configuration/config_files/).

            Setting this option will disable `[{cls.options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.

            If using isort 5+ and you specify only 1 config file, Pants will configure
            isort's argv to point to your config file.
            """
        ),
    )
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant config files during
            runs (`.isort.cfg`, `pyproject.toml`, `setup.cfg`, `tox.ini` and `.editorconfig`).

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to https://pycqa.github.io/isort/docs/configuration/config_files/.
        check_existence = []
        check_content = {}
        for d in ("", *dirs):
            check_existence.append(os.path.join(d, ".isort.cfg"))
            check_content.update(
                {
                    os.path.join(d, "pyproject.toml"): b"[tool.isort]",
                    os.path.join(d, "setup.cfg"): b"[isort]",
                    os.path.join(d, "tox.ini"): b"[isort]",
                    os.path.join(d, ".editorconfig"): b"[*.py]",
                }
            )

        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=check_existence,
            check_content=check_content,
        )


class IsortExportSentinel(ExportPythonToolSentinel):
    pass


@rule
def isort_export(_: IsortExportSentinel, isort: Isort) -> ExportPythonTool:
    if not isort.export:
        return ExportPythonTool(resolve_name=isort.options_scope, pex_request=None)
    return ExportPythonTool(resolve_name=isort.options_scope, pex_request=isort.to_pex_request())


def rules():
    return (
        *collect_rules(),
        UnionRule(ExportPythonToolSentinel, IsortExportSentinel),
    )
