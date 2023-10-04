# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Iterable

from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolBase
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.option.option_types import ArgsListOption, SkipOption
from pants.util.strutil import help_text


class Prettier(NodeJSToolBase):
    options_scope = "prettier"
    name = "Prettier"
    help = help_text(
        """
        The Prettier utility for formatting JS/TS (and others) code
        (https://prettier.io/).
        """
    )

    default_version = "prettier@2.6.2"

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--version")

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        """Prettier will use the closest configuration file to the file currently being formatted,
        so add all of them In the event of multiple configuration files, Prettier has an order of
        precedence specified here: https://prettier.io/docs/en/configuration.html."""

        config_files = (
            *[f"prettier.config{ext}" for ext in [".js", ".cjs"]],
            *[
                f".prettierrc{ext}"
                for ext in [
                    "",
                    ".json",
                    ".yml",
                    ".yaml",
                    ".json5",
                    ".js",
                    ".cjs",
                    ".toml",
                ]
            ],
        )
        check_existence = [os.path.join(d, file) for file in config_files for d in ("", *dirs)]
        return ConfigFilesRequest(
            discovery=True,
            check_existence=check_existence,
        )
