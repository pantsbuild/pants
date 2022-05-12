# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import BoolOption


class Protoc(TemplatedExternalTool):
    options_scope = "protoc"
    help = "The protocol buffer compiler (https://developers.google.com/protocol-buffers)."

    default_version = "3.20.1"
    default_known_versions = [
        "3.20.1|linux_arm64 |8a5a51876259f934cd2acc2bc59dba0e9a51bd631a5c37a4b9081d6e4dbc7591|1804837",
        "3.20.1|linux_x86_64|3a0e900f9556fbcac4c3a913a00d07680f0fdf6b990a341462d822247b265562|1714731",
        "3.20.1|macos_arm64 |b362acae78542872bb6aac8dba73aaf0dc6e94991b8b0a065d6c3e703fec2a8b|2708249",
        "3.20.1|macos_x86_64|b4f36b18202d54d343a66eebc9f8ae60809a2a96cc2d1b378137550bbe4cf33c|2708249",
    ]
    default_url_template = (
        "https://github.com/protocolbuffers/protobuf/releases/download/"
        "v{version}/protoc-{version}-{platform}.zip"
    )
    default_url_platform_mapping = {
        "linux_arm64": "linux-aarch_64",
        "linux_x86_64": "linux-x86_64",
        "macos_arm64": "osx-aarch_64",
        "macos_x86_64": "osx-x86_64",
    }

    dependency_inference = BoolOption(
        "--dependency-inference",
        default=True,
        help="Infer Protobuf dependencies on other Protobuf files by analyzing import statements.",
    )

    def generate_exe(self, plat: Platform) -> str:
        return "./bin/protoc"
