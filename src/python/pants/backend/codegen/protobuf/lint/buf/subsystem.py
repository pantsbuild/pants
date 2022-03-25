# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import ArgsListOption, SkipOption


class BufSubsystem(TemplatedExternalTool):
    options_scope = "buf"
    name = "Buf"
    help = "A linter and formatter for Protocol Buffers (https://github.com/bufbuild/buf)."

    default_version = "v1.3.0"
    default_known_versions = [
        "v1.3.0|linux_arm64 |fbfd53c501451b36900247734bfa4cbe86ae05d0f51bc298de8711d5ee374ee5|13940828",
        "v1.3.0|linux_x86_64|e29c4283b1cd68ada41fa493171c41d7605750d258fcd6ecdf692a63fae95213|15267162",
        "v1.3.0|macos_arm64 |147985d7f2816a545792e38b26178ff4027bf16cd3712f6e387a4e3692a16deb|15391890",
        "v1.3.0|macos_x86_64|3b6bd2e5a5dd758178aee01fb067261baf5d31bfebe93336915bfdf7b21928c4|15955291",
    ]
    default_url_template = (
        "https://github.com/bufbuild/buf/releases/download/{version}/buf-{platform}.tar.gz"
    )
    default_url_platform_mapping = {
        "macos_arm64": "Darwin-arm64",
        "macos_x86_64": "Darwin-x86_64",
        "linux_arm64": "Linux-aarch64",
        "linux_x86_64": "Linux-x86_64",
    }

    skip_format = SkipOption("fmt", "lint", flag_name="--format-skip")
    skip_lint = SkipOption("lint", flag_name="--lint-skip")
    format_args = ArgsListOption(example="--error-format json", flag_name="--format-args")
    lint_args = ArgsListOption(example="--error-format json", flag_name="--lint-args")

    def generate_exe(self, plat: Platform) -> str:
        return "./buf/bin/buf"
