# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.backend.python.util_rules.pex_requirements import GeneratePythonToolLockfileSentinel
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption, StrListOption, StrOption
from pants.util.docutil import git_url
from pants.util.strutil import softwrap


class Yamllint(PythonToolBase):
    name = "Yamllint"
    options_scope = "yamllint"
    help = "A linter for YAML files (https://yamllint.readthedocs.io)"

    default_version = "yamllint==1.29.0"
    default_main = ConsoleScript("yamllint")
    default_requirements = ["yamllint>=1.28.0,<2"]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.tools.yamllint", "yamllint.lock")
    default_lockfile_path = "src/python/pants/backend/tools/yamllint/yamllint.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    export = ExportToolOption()

    config_file_name = StrOption(
        "--config-file-name",
        default=".yamllint",
        advanced=True,
        help=softwrap(
            """
            Name of a config file understood by yamllint (https://yamllint.readthedocs.io/en/stable/configuration.html).
            The plugin will search the ancestors of each directory in which YAML files are found for a config file of this name.
            """
        ),
    )

    file_glob_include = StrListOption(
        "--include",
        default=["**/*.yml", "**/*.yaml"],
        help="Glob for which YAML files to lint.",
    )

    file_glob_exclude = StrListOption(
        "--exclude",
        default=[],
        help="Glob for which YAML files to exclude from linting.",
    )

    args = ArgsListOption(example="-d relaxed")

    skip = SkipOption("lint")


class YamllintLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = Yamllint.options_scope


@rule
def setup_yamllint_lockfile(
    _: YamllintLockfileSentinel, yamllint: Yamllint
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(yamllint)


class YamllintExportSentinel(ExportPythonToolSentinel):
    pass


@rule
def yamllint_export(_: YamllintExportSentinel, yamllint: Yamllint) -> ExportPythonTool:
    if not yamllint.export:
        return ExportPythonTool(resolve_name=yamllint.options_scope, pex_request=None)
    return ExportPythonTool(
        resolve_name=yamllint.options_scope, pex_request=yamllint.to_pex_request()
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, YamllintLockfileSentinel),
        UnionRule(ExportPythonToolSentinel, YamllintExportSentinel),
    )
