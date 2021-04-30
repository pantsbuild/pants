# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.option.custom_types import file_option, shell_str


class Isort(PythonToolBase):
    options_scope = "isort"
    help = "The Python import sorter tool (https://timothycrosley.github.io/isort/)."

    default_version = "isort[pyproject]>=5.5.1,<5.6"
    default_extra_requirements = ["setuptools"]
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]
    default_main = ConsoleScript("isort")

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=(
                f"Don't use isort when running `{register.bootstrap.pants_bin_name} fmt` and "
                f"`{register.bootstrap.pants_bin_name} lint`."
            ),
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to isort, e.g. "
                f'`--{cls.options_scope}-args="--case-sensitive --trailing-comma"`.'
            ),
        )
        register(
            "--config",
            type=list,
            member_type=file_option,
            advanced=True,
            help="Path to `isort.cfg` or alternative isort config file(s).",
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> tuple[str, ...]:
        return tuple(self.options.args)

    @property
    def config(self) -> tuple[str, ...]:
        return tuple(self.options.config)

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to https://pycqa.github.io/isort/docs/configuration/config_files/.
        check_existence = []
        check_content = {}
        for d in ("", *dirs):
            check_existence.append(os.path.join(d, ".isort.cfg"))
            check_content.update(
                {
                    os.path.join(d, "pyproject.toml"): b"[tool.isort]",
                    os.path.join(d, "setup.cfg"): b"[isort]",
                    os.path.join(d, "tox.ini"): b"[isort]",
                    os.path.join(d, ".editorconfig"): b"[*.py]",
                }
            )

        return ConfigFilesRequest(
            specified=self.config,
            check_existence=check_existence,
            check_content=check_content,
            option_name=f"[{self.options_scope}].config",
        )
