# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, cast

from pants.core.util_rules.external_tool import ExternalTool
from pants.engine.platform import Platform
from pants.option.custom_types import target_option
from pants.util.enums import match


class Protoc(ExternalTool):
    """The protocol buffer compiler (https://developers.google.com/protocol-buffers)."""

    options_scope = "protoc"
    default_version = "3.11.4"
    default_known_versions = [
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
        version = self.options.version
        plat_str = match(plat, {Platform.darwin: "osx", Platform.linux: "linux"})
        return (
            f"https://github.com/protocolbuffers/protobuf/releases/download/"
            f"v{version}/protoc-{version}-{plat_str}-x86_64.zip"
        )

    def generate_exe(self, plat: Platform) -> str:
        return "bin/protoc"

    @property
    def runtime_targets(self) -> List[str]:
        return cast(List[str], self.options.runtime_targets)
