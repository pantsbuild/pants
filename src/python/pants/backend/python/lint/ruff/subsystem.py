# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.lint.ruff.skip_field import SkipRuffField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonResolveField,
    PythonSourceField,
)
from pants.backend.python.util_rules import python_sources
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules
from pants.engine.target import FieldSet, Target
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class RuffFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    resolve: PythonResolveField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipRuffField).value


# --------------------------------------------------------------------------------------
# Subsystem
# --------------------------------------------------------------------------------------


class Ruff(PythonToolBase):
    options_scope = "ruff"
    name = "Ruff"
    help = "The Ruff Python formatter (https://github.com/astral-sh/ruff)."

    default_main = ConsoleScript("ruff")
    default_requirements = ["ruff>=0.1.2,<1"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.ruff", "ruff.lock")

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--exclude=foo --ignore=E501")
    config = FileOption(
        default=None,
        advanced=True,
        help=softwrap(
            f"""
            Path to the `pyproject.toml` or `ruff.toml` file to use for configuration
            (https://github.com/astral-sh/ruff#configuration).

            Setting this option will disable `[{options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.
            """
        ),
    )
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=softwrap(
            f"""
            If true, Pants will include any relevant config files during
            runs (`pyproject.toml`, and `ruff.toml`).

            Use `[{options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # See https://github.com/astral-sh/ruff#configuration for how ruff discovers
        # config files.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=["ruff.toml", *(os.path.join(d, "ruff.toml") for d in ("", *dirs))],
            check_content={"pyproject.toml": b"[tool.ruff"},
        )


def rules():
    return (
        *collect_rules(),
        *python_sources.rules(),
    )
