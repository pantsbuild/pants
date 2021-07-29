# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, cast

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform


class Protoc(TemplatedExternalTool):
    options_scope = "protoc"
    help = "The protocol buffer compiler (https://developers.google.com/protocol-buffers)."

    default_version = "3.11.4"
    default_known_versions = [
        "3.11.4|linux_x86_64|6d0f18cd84b918c7b3edd0203e75569e0c8caecb1367bbbe409b45e28514f5be|1591191",
        "3.11.4|macos_arm64 |8c6af11e1058efe953830ecb38324c0e0fd2fb67df3891896d138c535932e7db|2482119",
        "3.11.4|macos_x86_64|8c6af11e1058efe953830ecb38324c0e0fd2fb67df3891896d138c535932e7db|2482119",
    ]
    default_url_template = (
        "https://github.com/protocolbuffers/protobuf/releases/download/"
        "v{version}/protoc-{version}-{platform}.zip"
    )
    default_url_platform_mapping = {
        "linux_x86_64": "linux-x86_64",
        "macos_arm64": "osx-x86_64",  # May require rosetta, but output is arch-independent
        "macos_x86_64": "osx-x86_64",
    }

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--dependency-inference",
            default=True,
            type=bool,
            help=(
                "Infer Protobuf dependencies on other Protobuf files by analyzing import "
                "statements."
            ),
        )

    def generate_exe(self, plat: Platform) -> str:
        return "./bin/protoc"

    @property
    def runtime_targets(self) -> List[str]:
        return cast(List[str], self.options.runtime_targets)

    @property
    def dependency_inference(self) -> bool:
        return cast(bool, self.options.dependency_inference)
