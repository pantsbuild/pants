# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, cast

from pants.core.util_rules.external_tool import ExternalTool, ExternalToolError
from pants.engine.platform import Platform
from pants.option.custom_types import target_option


class Protoc(ExternalTool):
    options_scope = "protoc"
    default_version = "3.11.4"
    default_known_versions = [
        "2.4.1|darwin|d7bb59a067e6f5321499e6be4f6f6d5862693274e12d0cb9405596a34ba13d67|1953956",
        "2.4.1|linux |917d3b142da371ba466f2c853429815d1874bc77fc7d24cf65c82cf3718ef857|18589557",
        "3.11.4|darwin|8c6af11e1058efe953830ecb38324c0e0fd2fb67df3891896d138c535932e7db|2482119",
        "3.11.4|linux |6d0f18cd84b918c7b3edd0203e75569e0c8caecb1367bbbe409b45e28514f5be|1591191",
    ]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--runtime-targets",
            type=list,
            member_type=target_option,
            advanced=True,
            help=(
                "A list of addresses to targets for Protobuf runtime libraries. For example, a "
                "`python_requirement_library` for the `protobuf` Python library. These targets "
                "will be automatically injected into the `dependencies` field of every "
                "`protobuf_library`."
            ),
        )

    def generate_url(self, plat: Platform) -> str:
        version = self.get_options().version
        if version in {"2.4.1", "2.5.0", "2.6.1"}:
            # Very old versions of protoc don't have binaries available in their github releases.
            # So for now we rely on the pants-hosted binaries.
            # TODO: Get rid of or update our tests that rely on this very old version.
            #  Then we can consider whether to stop supporting it.
            if plat == Platform.darwin:
                plat_str = "mac/10.13"
            elif plat == Platform.linux:
                plat_str = "linux/x86_64"
            else:
                raise ExternalToolError()
            return f"https://binaries.pantsbuild.org/bin/protoc/{plat_str}/{version}/protoc"

        if plat == Platform.darwin:
            plat_str = "osx"
        elif plat == Platform.linux:
            plat_str = "linux"
        else:
            raise ExternalToolError()
        return (
            f"https://github.com/protocolbuffers/protobuf/releases/download/"
            f"v{version}/protoc-{version}-{plat_str}-x86_64.zip"
        )

    def generate_exe(self, plat: Platform) -> str:
        version = self.get_options().version
        if version in {"2.4.1", "2.5.0", "2.6.1"}:
            return "protoc"
        else:
            return "bin/protoc"

    @property
    def runtime_targets(self) -> List[str]:
        return cast(List[str], self.options.runtime_targets)
