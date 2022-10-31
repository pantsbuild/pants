# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.option.option_types import ArgsListOption, SkipOption


class SpectralSubsystem(TemplatedExternalTool):
    options_scope = "spectral"
    name = "Spectral"
    help = "A flexible JSON/YAML linter for creating automated style guides (https://github.com/stoplightio/spectral)."

    default_version = "v6.5.1"
    default_known_versions = [
        "v6.5.1|linux_arm64 |81017af87e04711ab0a0a7c15af9985241f6c84101d039775057bbec17572916|72709153",
        "v6.5.1|linux_x86_64|81017af87e04711ab0a0a7c15af9985241f6c84101d039775057bbec17572916|72709153",
        "v6.5.1|macos_arm64 |5b10d772cb309d82b6a49b689ed58580dcb3393ead82b82ab648eead7da4bd79|77446257",
        "v6.5.1|macos_x86_64|5b10d772cb309d82b6a49b689ed58580dcb3393ead82b82ab648eead7da4bd79|77446257",
    ]
    default_url_template = (
        "https://github.com/stoplightio/spectral/releases/download/{version}/spectral-{platform}"
    )
    default_url_platform_mapping = {
        "macos_arm64": "macos",
        "macos_x86_64": "macos",
        "linux_arm64": "linux",
        "linux_x86_64": "linux",
    }

    skip = SkipOption("lint")
    args = ArgsListOption(example="--fail-severity=warn")
