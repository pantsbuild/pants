# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.lint.ruff.skip_field import SkipRuffField
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonResolveField,
    PythonSourceField,
)
from pants.backend.python.util_rules import python_sources
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.docutil import git_url
from pants.util.logging import LogLevel
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
    help = "The Ruff Python formatter (https://github.com/charliermarsh/ruff)."

    default_version = "ruff==0.0.254"
    default_main = ConsoleScript("ruff")
    default_requirements = ["ruff>=0.0.213,<0.1"]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.ruff", "ruff.lock")
    default_lockfile_path = "src/python/pants/backend/python/lint/ruff/ruff.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--exclude=foo --ignore=E501")
    export = ExportToolOption()
    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to the `pyproject.toml` or `ruff.toml` file to use for configuration
            (https://github.com/charliermarsh/ruff#configuration).

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
            runs (`pyproject.toml`, and `ruff.toml`).

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # See https://github.com/charliermarsh/ruff#configuration for how ruff discovers
        # config files.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=["ruff.toml", *(os.path.join(d, "ruff.toml") for d in ("", *dirs))],
            check_content={"pyproject.toml": b"[tool.ruff"},
        )


# --------------------------------------------------------------------------------------
# Lockfile
# --------------------------------------------------------------------------------------


class RuffLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = Ruff.options_scope


@rule(
    desc=softwrap(
        """
        Determine all Python interpreter versions used by ruff in your project
        (for lockfile generation)
        """
    ),
    level=LogLevel.DEBUG,
)
async def setup_ruff_lockfile(_: RuffLockfileSentinel, ruff: Ruff) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(ruff)


# --------------------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------------------


class RuffExportSentinel(ExportPythonToolSentinel):
    pass


@rule(
    desc=softwrap(
        """
        Determine all Python interpreter versions used by ruff in your project
        (for `export` goal)
        """
    ),
    level=LogLevel.DEBUG,
)
async def ruff_export(_: RuffExportSentinel, ruff: Ruff) -> ExportPythonTool:
    if not ruff.export:
        return ExportPythonTool(resolve_name=ruff.options_scope, pex_request=None)
    return ExportPythonTool(
        resolve_name=ruff.options_scope,
        pex_request=ruff.to_pex_request(),
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        *python_sources.rules(),
        UnionRule(GenerateToolLockfileSentinel, RuffLockfileSentinel),
        UnionRule(ExportPythonToolSentinel, RuffExportSentinel),
    )
