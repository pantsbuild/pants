# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import ExternalTool, ExternalToolError
from pants.engine.platform import Platform


class Protoc(ExternalTool):
    options_scope = "protoc"
    default_version = "3.11.999"
    default_known_versions = [
        "3.11.4|darwin|8c6af11e1058efe953830ecb38324c0e0fd2fb67df3891896d138c535932e7db|2482119",
        "3.11.4|linux |6d0f18cd84b918c7b3edd0203e75569e0c8caecb1367bbbe409b45e28514f5be|1591191",
    ]

    @classmethod
    def generate_url(cls, plat: Platform, version: str) -> str:
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

    @classmethod
    def generate_exe(cls, plat: Platform, version: str) -> str:
        return "bin/protoc"
