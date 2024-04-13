# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.lint.black.skip_field import SkipBlackField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonSourceField,
)
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class BlackFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipBlackField).value


class Black(PythonToolBase):
    options_scope = "black"
    name = "Black"
    help_short = "The Black Python code formatter (https://black.readthedocs.io/)."

    default_main = ConsoleScript("black")
    default_requirements = [
        "black>=22.6.0,<24",
        'typing-extensions>=3.10.0.0; python_version < "3.10"',
    ]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.black", "black.lock")

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--target-version=py37 --quiet")
    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to a TOML config file understood by Black
            (https://github.com/psf/black#configuration-format).

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
            If true, Pants will include any relevant pyproject.toml config files during runs.

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to https://black.readthedocs.io/en/stable/usage_and_configuration/the_basics.html#where-black-looks-for-the-file
        # for how Black discovers config.
        candidates = {os.path.join(d, "pyproject.toml"): b"[tool.black]" for d in ("", *dirs)}
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_content=candidates,
        )


def rules():
    return [
        *collect_rules(),
        UnionRule(ExportableTool, Black),
    ]
