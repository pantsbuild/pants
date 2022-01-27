# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable, cast

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.custom_types import file_option, shell_str
from pants.util.docutil import git_url


class Yapf(PythonToolBase):
    options_scope = "yapf"
    help = "A formatter for Python files (https://github.com/google/yapf)."

    default_version = "yapf==0.32.0"
    default_extra_requirements = ["toml"]
    default_main = ConsoleScript("yapf")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.yapf", "lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/lint/yapf/lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=(
                f"Don't use yapf when running `{register.bootstrap.pants_bin_name} fmt` and "
                f"`{register.bootstrap.pants_bin_name} lint`."
            ),
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to yapf, e.g. "
                f'`--{cls.options_scope}-args="--no-local-style"`.\n\n'
                "Certain arguments, specifically `--recursive`, `--in-place`, and "
                "`--parallel`, will be ignored because Pants takes care of finding "
                "all the relevant files and running the formatting in parallel."
            ),
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help=(
                "Path to style file understood by yapf "
                "(https://github.com/google/yapf#formatting-style/).\n\n"
                f"Setting this option will disable `[{cls.options_scope}].config_discovery`. Use "
                f"this option if the config is located in a non-standard location."
            ),
        )
        register(
            "--config-discovery",
            type=bool,
            default=True,
            advanced=True,
            help=(
                "If true, Pants will include any relevant config files during "
                "runs (`.style.yapf`, `pyproject.toml`, and `setup.cfg`)."
                f"\n\nUse `[{cls.options_scope}].config` instead if your config is in a "
                f"non-standard location."
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> tuple[str, ...]:
        return tuple(self.options.args)

    @property
    def config(self) -> str | None:
        return cast("str | None", self.options.config)

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
            discovery=cast(bool, self.options.config_discovery),
            check_existence=check_existence,
            check_content=check_content,
        )


class YapfLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = Yapf.options_scope


@rule
def setup_yapf_lockfile(_: YapfLockfileSentinel, yapf: Yapf) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(yapf)


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, YapfLockfileSentinel),
    )
