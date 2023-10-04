# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.strutil import softwrap


class Yapf(PythonToolBase):
    options_scope = "yapf"
    name = "yapf"
    help = "A formatter for Python files (https://github.com/google/yapf)."

    default_main = ConsoleScript("yapf")
    default_requirements = ["yapf>=0.32.0,<1", "toml"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.yapf", "yapf.lock")

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(
        example="--no-local-style",
        extra_help=softwrap(
            """
            Certain arguments, specifically `--recursive`, `--in-place`, and
            `--parallel`, will be ignored because Pants takes care of finding
            all the relevant files and running the formatting in parallel.
            """
        ),
    )
    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to style file understood by yapf
            (https://github.com/google/yapf#formatting-style/).

            Setting this option will disable `[{cls.options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.
            """
        ),
    )
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant config files during
            runs (`.style.yapf`, `pyproject.toml`, and `setup.cfg`).

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
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


def rules():
    return collect_rules()
