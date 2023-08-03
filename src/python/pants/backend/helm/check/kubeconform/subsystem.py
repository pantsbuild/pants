# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum, unique

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import BoolOption, EnumOption, IntOption, SkipOption, StrListOption


@unique
class KubeconformOutput(Enum):
    """The report format used for the unit tests."""

    TEXT = "text"
    JSON = "json"
    TAP = "tap"
    JUNIT = "junit"


class KubeconformSubsystem(TemplatedExternalTool):
    options_scope = "kubeconform"
    name = "kubeconform"
    help = "Kubeconform tool (https://github.com/yannh/kubeconform)"

    default_version = "0.6.2"
    default_url_template = "https://github.com/yannh/kubeconform/releases/download/v{version}/kubeconform-{platform}.tar.gz"
    default_known_versions = [
        "0.6.2|linux_arm64 |41c15ecbb120042bee0aca8a616e479b555084d5d14bc2e095ed96081c1e9404|5335394",
        "0.6.2|linux_x86_64|d2a10db6b78d56de8fe9375b9c351bc573aa218a74da04d114767b505a675090|5739066",
        "0.6.2|macos_arm64 |881e3fe2ecdb1cc41bce80013113f24da80e1bec593876ffe88668333ae69b51|5423607",
        "0.6.2|macos_x86_64|88e53c2562482ed5ab7434188ca5ba03d3482088ac52d53da7499d579923f2e8|5656173",
    ]
    default_url_platform_mapping = {
        "linux_arm64": "linux-arm64",
        "linux_x86_64": "linux-amd64",
        "macos_arm64": "darwin-arm64",
        "macos_x86_64": "darwin-amd64",
    }

    skip = SkipOption("check")

    concurrency = IntOption(
        default=None,
        help="Number of workers used by Kubeconform to validate resources.",
        advanced=True,
    )
    schema_locations = StrListOption(
        default=["default"],
        help="List of schema locations to use to validate the resources.",
        advanced=True,
    )
    output_type = EnumOption(
        default=KubeconformOutput.TEXT, help="Output type used by `kubeconform`."
    )
    summary = BoolOption(default=False, help="Set to true to only output check summary.")
    verbose = BoolOption(default=False, help="Set to true to increase output verbosity.")

    def generate_exe(self, _: Platform) -> str:
        return "./kubeconform"
