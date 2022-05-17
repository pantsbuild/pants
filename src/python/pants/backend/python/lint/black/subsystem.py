# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.lint.black.skip_field import SkipBlackField
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import ConsoleScript
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import Get, collect_rules, rule, rule_helper
from pants.engine.target import AllTargets, AllTargetsRequest
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.docutil import git_url
from pants.util.logging import LogLevel


class Black(PythonToolBase):
    options_scope = "black"
    name = "Black"
    help = "The Black Python code formatter (https://black.readthedocs.io/)."

    default_version = "black==22.1.0"
    default_main = ConsoleScript("black")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.black", "black.lock")
    default_lockfile_path = "src/python/pants/backend/python/lint/black/black.lock"
    default_lockfile_url = git_url(default_lockfile_path)
    default_extra_requirements = ['typing-extensions>=3.10.0.0; python_version < "3.10"']

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--target-version=py37 --quiet")
    export = ExportToolOption()
    config = FileOption(
        "--config",
        default=None,
        advanced=True,
        help=lambda cls: (
            "Path to a TOML config file understood by Black "
            "(https://github.com/psf/black#configuration-format).\n\n"
            f"Setting this option will disable `[{cls.options_scope}].config_discovery`. Use "
            f"this option if the config is located in a non-standard location."
        ),
    )
    config_discovery = BoolOption(
        "--config-discovery",
        default=True,
        advanced=True,
        help=lambda cls: (
            "If true, Pants will include any relevant pyproject.toml config files during runs."
            f"\n\nUse `[{cls.options_scope}].config` instead if your config is in a "
            f"non-standard location."
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


@rule_helper
async def _black_interpreter_constraints(
    black: Black, python_setup: PythonSetup
) -> InterpreterConstraints:
    constraints = black.interpreter_constraints
    if black.options.is_default("interpreter_constraints"):
        all_tgts = await Get(AllTargets, AllTargetsRequest())
        # TODO: fix to use `FieldSet.is_applicable()`.
        code_constraints = InterpreterConstraints.create_from_targets(
            (tgt for tgt in all_tgts if not tgt.get(SkipBlackField).value), python_setup
        )
        if code_constraints.requires_python38_or_newer(python_setup.interpreter_universe):
            constraints = code_constraints
    return constraints


class BlackLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = Black.options_scope


@rule(
    desc="Determine Black interpreter constraints (for lockfile generation)",
    level=LogLevel.DEBUG,
)
async def setup_black_lockfile(
    _: BlackLockfileSentinel, black: Black, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    if not black.uses_custom_lockfile:
        return GeneratePythonLockfile.from_tool(
            black, use_pex=python_setup.generate_lockfiles_with_pex
        )

    constraints = await _black_interpreter_constraints(black, python_setup)
    return GeneratePythonLockfile.from_tool(
        black, constraints, use_pex=python_setup.generate_lockfiles_with_pex
    )


class BlackExportSentinel(ExportPythonToolSentinel):
    pass


@rule(desc="Determine Black interpreter constraints (for `export` goal)", level=LogLevel.DEBUG)
async def black_export(
    _: BlackExportSentinel, black: Black, python_setup: PythonSetup
) -> ExportPythonTool:
    if not black.export:
        return ExportPythonTool(resolve_name=black.options_scope, pex_request=None)
    constraints = await _black_interpreter_constraints(black, python_setup)
    return ExportPythonTool(
        resolve_name=black.options_scope,
        pex_request=black.to_pex_request(interpreter_constraints=constraints),
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, BlackLockfileSentinel),
        UnionRule(ExportPythonToolSentinel, BlackExportSentinel),
    )
