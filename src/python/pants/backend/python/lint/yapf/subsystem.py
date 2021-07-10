# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.option.custom_types import file_option, shell_str


class Yapf(PythonToolBase):
    options_scope = "yapf"
    help = "A formatter for Python files (https://github.com/google/yapf)."

    default_version = "yapf==0.31.0"
    default_extra_requirements = ["setuptools", "toml"]
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]
    default_main = ConsoleScript("yapf")

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
                f'`--{cls.options_scope}-args="--no-local-style"`.'
                "All flags except ... are ignored (because they are handled by Pants)"  # TODO(alte)
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
                "runs (`.style.yapf`, `pyproject.toml`, `setup.cfg`, and `~/.config/yapf/style`)."
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
        check_content = {}
        for d in ("", *dirs):
            check_content.update(
                {
                    os.path.join(d, "pyproject.toml"): b"[tool.yapf]",
                    os.path.join(d, "setup.cfg"): b"[yapf]",
                    os.path.join(d, ".style.yapf"): b"[style]",
                    "~/.config/yapf/style": b"[style]",
                    os.path.join(d, ".yapfignore"): b"",
                }
            )

        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=cast(bool, self.options.config_discovery),
            check_content=check_content,
        )
