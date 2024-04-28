# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from experimental.sql.lint.sqlfluff.skip_field import SkipSqlfluffField
from experimental.sql.target_types import SqlDialectField, SqlSourceField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonResolveField,
    PythonSourceField,
)
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules
from pants.engine.target import FieldSet, Target
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class SqlfluffFieldSet(FieldSet):
    required_fields = (SqlSourceField,)

    source: SqlSourceField
    dialect: SqlDialectField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipSqlfluffField).value


class SqlfluffMode(str, Enum):
    LINT = "lint"
    FIX = "fix"
    FMT = "format"


# --------------------------------------------------------------------------------------
# Subsystem
# --------------------------------------------------------------------------------------


class Sqlfluff(PythonToolBase):
    options_scope = "sqlfluff"
    name = "Sqlfluff"
    help = "The Sqlfluff SQL linter (https://github.com/sqlfluff/sqlfluff)."

    default_main = ConsoleScript("sqlfluff")
    default_requirements = ["sqlfluff>=2.3.5,<3"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("experimental.sql.lint.sqlfluff", "sqlfluff.lock")

    skip = SkipOption("fmt", "fix", "lint")
    args = ArgsListOption(example="--exclude=foo --ignore=E501")
    config = FileOption(
        default=None,
        advanced=True,
        help=softwrap(
            f"""
            Path to the `pyproject.toml` or `.sqlfluff` file to use for configuration
            (https://docs.sqlfluff.com/en/stable/configuration.html).

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
            runs (`pyproject.toml`, and `.sqlfluff`).

            Use `[{options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # See https://docs.sqlfluff.com/en/stable/configuration.html for how sqlfluff discovers
        # config files.
        all_dirs = ("", *dirs)
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[os.path.join(d, ".sqlfluff") for d in all_dirs],
            check_content={os.path.join(d, "pyproject.toml"): b"[tool.sqlfluff" for d in all_dirs},
        )


def rules():
    return (*collect_rules(),)
