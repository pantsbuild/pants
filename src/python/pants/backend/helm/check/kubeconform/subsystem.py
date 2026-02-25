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

    default_version = "0.7.0"
    default_url_template = "https://github.com/yannh/kubeconform/releases/download/v{version}/kubeconform-{platform}.tar.gz"
    default_known_versions = [
        "0.7.0|linux_arm64 |cc907ccf9e3c34523f0f32b69745265e0a6908ca85b92f41931d4537860eb83c|6982794",
        "0.7.0|linux_x86_64|c31518ddd122663b3f3aa874cfe8178cb0988de944f29c74a0b9260920d115d3|7491807",
        "0.7.0|macos_arm64 |b5d32b2cb77f9c781c976b20a85e2d0bc8f9184d5d1cfe665a2f31a19f99eeb9|7031569",
        "0.7.0|macos_x86_64|c6771cc894d82e1b12f35ee797dcda1f7da6a3787aa30902a15c264056dd40d4|7420234",
        "0.6.7|linux_arm64 |dc82f79bb03c5479b1ae5fd4af221e4b5a3111f62bf01a2795d9c5c20fa96644|5841917",
        "0.6.7|linux_x86_64|95f14e87aa28c09d5941f11bd024c1d02fdc0303ccaa23f61cef67bc92619d73|6264184",
        "0.6.7|macos_arm64 |cbb47d938a8d18eb5f79cb33663b2cecdee0c8ac0bf562ebcfca903df5f0802f|5907133",
        "0.6.7|macos_x86_64|3b5324ac4fd38ac60a49823b4051ff42ff7eb70144f1e9741fed1d14bc4fdb4e|6225509",
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
