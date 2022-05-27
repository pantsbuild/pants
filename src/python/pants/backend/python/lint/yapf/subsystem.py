# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.docutil import git_url


class Yapf(PythonToolBase):
    options_scope = "yapf"
    name = "yapf"
    help = "A formatter for Python files (https://github.com/google/yapf)."

    default_version = "yapf==0.32.0"
    default_extra_requirements = ["toml"]
    default_main = ConsoleScript("yapf")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.yapf", "yapf.lock")
    default_lockfile_path = "src/python/pants/backend/python/lint/yapf/yapf.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(
        example="--no-local-style",
        extra_help="Certain arguments, specifically `--recursive`, `--in-place`, and "
        "`--parallel`, will be ignored because Pants takes care of finding "
        "all the relevant files and running the formatting in parallel.",
    )
    export = ExportToolOption()
    config = FileOption(
        "--config",
        default=None,
        advanced=True,
        help=lambda cls: (
            "Path to style file understood by yapf "
            "(https://github.com/google/yapf#formatting-style/).\n\n"
            f"Setting this option will disable `[{cls.options_scope}].config_discovery`. Use "
            f"this option if the config is located in a non-standard location."
        ),
    )
    config_discovery = BoolOption(
        "--config-discovery",
        default=True,
        advanced=True,
        help=lambda cls: (
            "If true, Pants will include any relevant config files during "
            "runs (`.style.yapf`, `pyproject.toml`, and `setup.cfg`)."
            f"\n\nUse `[{cls.options_scope}].config` instead if your config is in a "
            f"non-standard location."
        ),
    )

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to https://github.com/google/yapf#formatting-style.
        check_existence = []
        check_content = {}
        for d in ("", *dirs):
            check_existence.append(os.path.join(d, ".yapfignore"))
            check_content.update(
                {
                    os.path.join(d, "pyproject.toml"): b"[tool.yapf",
                    os.path.join(d, "setup.cfg"): b"[yapf]",
                    os.path.join(d, ".style.yapf"): b"[style]",
                }
            )

        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=check_existence,
            check_content=check_content,
        )


class YapfLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = Yapf.options_scope


@rule
def setup_yapf_lockfile(
    _: YapfLockfileSentinel, yapf: Yapf, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(yapf, use_pex=python_setup.generate_lockfiles_with_pex)


class YapfExportSentinel(ExportPythonToolSentinel):
    pass


@rule
def yapf_export(_: YapfExportSentinel, yapf: Yapf) -> ExportPythonTool:
    if not yapf.export:
        return ExportPythonTool(resolve_name=yapf.options_scope, pex_request=None)
    return ExportPythonTool(resolve_name=yapf.options_scope, pex_request=yapf.to_pex_request())


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, YapfLockfileSentinel),
        UnionRule(ExportPythonToolSentinel, YapfExportSentinel),
    )
