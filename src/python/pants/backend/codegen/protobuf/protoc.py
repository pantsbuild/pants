# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption


class Protoc(TemplatedExternalTool):
    options_scope = "protoc"
    help = "The protocol buffer compiler (https://developers.google.com/protocol-buffers)."

    default_version = "30.2"
    default_known_versions = [
        "30.2|linux_arm64 |a3173ea338ef91b1605b88c4f8120d6c8ccf36f744d9081991d595d0d4352996|3324324",
        "30.2|linux_x86_64|327e9397c6fb3ea2a542513a3221334c6f76f7aa524a7d2561142b67b312a01f|3364030",
        "30.2|macos_arm64 |92728c650f6cf2b6c37891ae04ef5bc2d4b5f32c5fbbd101eda623f90bb95f63|2344514",
        "30.2|macos_x86_64|65675c3bb874a2d5f0c941e61bce6175090be25fe466f0ec2d4a6f5978333624|2469884",
        "25.2|linux_arm64 |07683afc764e4efa3fa969d5f049fbc2bdfc6b4e7786a0b233413ac0d8753f6b|3071655",
        "25.2|linux_x86_64|78ab9c3288919bdaa6cfcec6127a04813cf8a0ce406afa625e48e816abee2878|3105555",
        "25.2|macos_arm64 |8822b090c396800c96ac652040917eb3fbc5e542538861aad7c63b8457934b20|2209071",
        "25.2|macos_x86_64|5fe89993769616beff1ed77408d1335216379ce7010eee80284a01f9c87c8888|2235343",
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


def rules():
    return (UnionRule(ExportableTool, Protoc),)
