# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolBase, bundled_lockfiles
from pants.option.option_types import ArgsListOption, SkipOption


class SpectralSubsystem(NodeJSToolBase):
    options_scope = "spectral"
    name = "Spectral"
    help = "A flexible JSON/YAML linter for creating automated style guides (https://github.com/stoplightio/spectral)."

    default_version = "@stoplight/spectral-cli@6.5.1"
    default_lockfile_resources = bundled_lockfiles(__package__, "spectral")

    skip = SkipOption("lint")
    args = ArgsListOption(example="--fail-severity=warn")

    @property
    def binary_name(self) -> str:
        """The binary name to run for this tool."""
        return self._binary_name or "spectral"
