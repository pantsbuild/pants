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
        "24.4|linux_arm64 |83ac000ff540e242b6a2ff221a3ac88d2d8e55443801b7a28e9697e5f40e8937|2971447",
        "24.4|linux_x86_64|5871398dfd6ac954a6adebf41f1ae3a4de915a36a6ab2fd3e8f2c00d45b50dec|3005774",
        "24.4|macos_arm64 |d80544480397fe8a05d966fba291cf1233ad0db0ebc24ec72d7bd077d6e7ac59|2088802",
        "24.4|macos_x86_64|6c3b6bf4038d733b6d31f1cc4516a656570b5b5aafb966b650f8182afd0b98cf|2121366",
        "3.20.1|linux_arm64 |8a5a51876259f934cd2acc2bc59dba0e9a51bd631a5c37a4b9081d6e4dbc7591|1804837",
        "3.20.1|linux_x86_64|3a0e900f9556fbcac4c3a913a00d07680f0fdf6b990a341462d822247b265562|1714731",
        # 3.20.1|macos_arm64 below is an x86 binary. Needs Rosetta to run on Apple Silicon.
        # see https://github.com/protocolbuffers/protobuf/issues/9893
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
        default=True,
        help="Infer Protobuf dependencies on other Protobuf files by analyzing import statements.",
    )
    tailor = BoolOption(
        default=True,
        help="If true, add `protobuf_sources` targets with the `tailor` goal.",
        advanced=True,
    )

    def generate_exe(self, plat: Platform) -> str:
        return "./bin/protoc"
