from __future__ import annotations

import os.path
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.backend.sql.lint.sqlfluff.skip_field import SkipSqlfluffField
from pants.backend.sql.target_types import SqlSourceField
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules
from pants.engine.target import FieldSet, Target
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class SqlfluffFieldSet(FieldSet):
    required_fields = (SqlSourceField,)

    source: SqlSourceField

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
    default_requirements = ["sqlfluff>=3.0.5,<4"]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.8,<4"]

    default_lockfile_resource = ("pants.backend.sql.lint.sqlfluff", "sqlfluff.lock")

    skip = SkipOption("fmt", "fix", "lint")
    args = ArgsListOption(example="--dialect=postgres --exclude-rules LT08,RF02")
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
        # See https://docs.sqlfluff.com/en/stable/configuration.html for how
        # sqlfluff discovers config files.
        all_dirs = ("", *dirs)
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[
                os.path.join(d, filename)
                for d in all_dirs
                for filename in ["setup.cfg", "tox.ini", "pep8.ini", ".sqlfluff"]
            ],
            check_content={os.path.join(d, "pyproject.toml"): b"[tool.sqlfluff" for d in all_dirs},
        )


def rules():
    return collect_rules()
