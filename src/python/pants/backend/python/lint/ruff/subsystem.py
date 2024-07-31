# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from enum import Enum
from typing import Iterable

from pants.backend.python.util_rules import python_sources
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule
from pants.option.option_types import (
    ArgsListOption,
    BoolOption,
    FileOption,
    SkipOption,
    StrListOption,
    StrOption,
)
from pants.util.strutil import softwrap


class RuffMode(str, Enum):
    FIX = "check --fix"
    FORMAT = "format"
    LINT = "check"
    # "format --check" is automatically covered by builtin linter for RuffFmtRequest.


# --------------------------------------------------------------------------------------
# Subsystem
# --------------------------------------------------------------------------------------


class Ruff(TemplatedExternalTool):
    options_scope = "ruff"
    name = "Ruff"
    help = "The Ruff Python formatter (https://github.com/astral-sh/ruff)."

    default_version = "0.4.9"
    default_known_versions = [
        # Custom URls because the tagging scheme changed from `v0.4.x` (Note: v) to `0.5.x`:
        "0.4.9|macos_arm64|5f4506d7ec2ae6ac5a48ba309218a4b825a00d4cad9967b7bbcec1724ef04930|8148128|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-aarch64-apple-darwin.tar.gz",
        "0.4.9|macos_x86_64|e4d745adb0f5a0b08f2c9ca71e57f451a9b8485ae35b5555d9f5d20fc93a6cb6|8510706|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-x86_64-apple-darwin.tar.gz",
        "0.4.9|linux_arm64|00c50563f9921a141ddd4ec0371149f3bbfa0369d9d238a143bcc3a932363785|8106747|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-aarch64-unknown-linux-musl.tar.gz",
        "0.4.9|linux_x86_64|5ceba21dad91e3fa05056ca62f278b0178516cfad8dbf08cf2433c6f1eeb92d3|8863118|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-x86_64-unknown-linux-musl.tar.gz",
    ]
    version_constraints = ">=0.1.2,<1"

    default_url_template = "https://github.com/astral-sh/ruff/releases/download/v{version}/ruff-{version}-{platform}.tar.gz"
    default_url_platform_mapping = {
        # NB. musl not gnu, for increased compatibility
        "linux_arm64": "aarch64-unknown-linux-musl",
        "linux_x86_64": "x86_64-unknown-linux-musl",
        "macos_arm64": "aarch64-apple-darwin",
        "macos_x86_64": "x86_64-apple-darwin",
    }

    def generate_exe(self, plat: Platform) -> str:
        return "./ruff"

    skip = SkipOption("fmt", "fix", "lint")
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
        all_dirs = ("", *dirs)
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[os.path.join(d, "ruff.toml") for d in all_dirs],
            check_content={os.path.join(d, "pyproject.toml"): b"[tool.ruff" for d in all_dirs},
        )

    # Options that only exist to ease the upgrade from Ruff as a Python tool to Ruff as an external
    # downloaded one
    install_from_resolve = StrOption(
        advanced=True,
        default=None,
        removal_version="2.26.0.dev0",
        removal_hint="Now ignored: use `version` and `known_version` to customise the version, consider deleting the resolve and `python_requirement` if no longer used",
        help="Formerly used to customise the version of Ruff to install.",
    )

    requirements = StrListOption(
        advanced=True,
        default=None,
        removal_version="2.26.0.dev0",
        removal_hint="Now ignored: use `version` and `known_version` to customise the version, consider deleting the resolve and `python_requirement` if no longer used",
        help="Formerly used to customise the version of Ruff to install.",
    )
    interpreter_constraints = StrListOption(
        advanced=True,
        default=None,
        removal_version="2.26.0.dev0",
        removal_hint="Now ignored: use `version` and `known_version` to customise the version, consider deleting the resolve and `python_requirement` if no longer used",
        help="Formerly used to customise the version of Ruff to install.",
    )
    console_script = StrOption(
        advanced=True,
        default=None,
        removal_version="2.26.0.dev0",
        removal_hint="Now ignored: use `version` and `known_version` to customise the version, consider deleting the resolve and `python_requirement` if no longer used",
        help="Formerly used to customise the version of Ruff to install.",
    )
    entry_point = StrOption(
        advanced=True,
        default=None,
        removal_version="2.26.0.dev0",
        removal_hint="Now ignored: use `version` and `known_version` to customise the version, consider deleting the resolve and `python_requirement` if no longer used",
        help="Formerly used to customise the version of Ruff to install.",
    )


def rules():
    return (
        *collect_rules(),
        *python_sources.rules(),
        UnionRule(ExportableTool, Ruff),
    )
