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
from pants.util.docutil import doc_url
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

    default_version = "0.6.4"
    default_known_versions = [
        "0.6.4|macos_arm64|2648dd09984c82db9f3163ce8762c89536e4bf0e198f17e06a01c0e32214273e|9167424",
        "0.6.4|macos_x86_64|4438cbc80c6aa0e839abc3abb2a869a27113631cb40aa26540572fb53752c432|9463378",
        "0.6.4|linux_arm64|a9157a0f062d62c1b1582284a8d10629503f38bc9b7126b614cb7569073180ff|10120541",
        "0.6.4|linux_x86_64|3ca04aabf7259c59193e4153a865618cad26f73be930ce5f6109e0e6097d037b|10373921",
        # Custom URLs because 0.5+ doesn't include the version
        "0.4.9|macos_arm64|5f4506d7ec2ae6ac5a48ba309218a4b825a00d4cad9967b7bbcec1724ef04930|8148128|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-aarch64-apple-darwin.tar.gz",
        "0.4.9|macos_x86_64|e4d745adb0f5a0b08f2c9ca71e57f451a9b8485ae35b5555d9f5d20fc93a6cb6|8510706|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-x86_64-apple-darwin.tar.gz",
        "0.4.9|linux_arm64|00c50563f9921a141ddd4ec0371149f3bbfa0369d9d238a143bcc3a932363785|8106747|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-aarch64-unknown-linux-musl.tar.gz",
        "0.4.9|linux_x86_64|5ceba21dad91e3fa05056ca62f278b0178516cfad8dbf08cf2433c6f1eeb92d3|8863118|https://github.com/astral-sh/ruff/releases/download/v0.4.9/ruff-0.4.9-x86_64-unknown-linux-musl.tar.gz",
    ]
    version_constraints = ">=0.1.2,<1"

    default_url_template = (
        "https://github.com/astral-sh/ruff/releases/download/{version}/ruff-{platform}.tar.gz"
    )
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

    _removal_hint = f"NOW IGNORED: use `version` and `known_versions` options to customise the version of ruff, replacing this option; consider deleting the resolve and `python_requirement` if no longer used. See {doc_url('reference/subsystems/ruff')}"

    # Options that only exist to ease the upgrade from Ruff as a Python tool to Ruff as an external
    # downloaded one
    install_from_resolve = StrOption(
        advanced=True,
        default=None,
        removal_version="2.26.0.dev0",
        removal_hint=_removal_hint,
        help="Formerly used to customise the version of Ruff to install.",
    )

    requirements = StrListOption(
        advanced=True,
        default=None,
        removal_version="2.26.0.dev0",
        removal_hint=_removal_hint,
        help="Formerly used to customise the version of Ruff to install.",
    )
    interpreter_constraints = StrListOption(
        advanced=True,
        default=None,
        removal_version="2.26.0.dev0",
        removal_hint=_removal_hint,
        help="Formerly used to customise the version of Ruff to install.",
    )
    console_script = StrOption(
        advanced=True,
        default=None,
        removal_version="2.26.0.dev0",
        removal_hint=_removal_hint,
        help="Formerly used to customise the version of Ruff to install.",
    )
    entry_point = StrOption(
        advanced=True,
        default=None,
        removal_version="2.26.0.dev0",
        removal_hint=_removal_hint,
        help="Formerly used to customise the version of Ruff to install.",
    )


def rules():
    return (
        *collect_rules(),
        *python_sources.rules(),
        UnionRule(ExportableTool, Ruff),
    )
