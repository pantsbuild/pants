# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, cast

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform


class Protoc(TemplatedExternalTool):
    """The protocol buffer compiler (https://developers.google.com/protocol-buffers)."""

    options_scope = "protoc"
    default_version = "3.11.4"
    default_known_versions = [
        "3.11.4|darwin|8c6af11e1058efe953830ecb38324c0e0fd2fb67df3891896d138c535932e7db|2482119",
        "3.11.4|linux |6d0f18cd84b918c7b3edd0203e75569e0c8caecb1367bbbe409b45e28514f5be|1591191",
    ]
    default_url_template = (
        "https://github.com/protocolbuffers/protobuf/releases/download/"
        "v{version}/protoc-{version}-{platform}-x86_64.zip"
    )
    default_url_platform_mapping = {
        "darwin": "osx",
        "linux": "linux",
    }

    def generate_exe(self, plat: Platform) -> str:
        return "./bin/protoc"

    @property
    def runtime_targets(self) -> List[str]:
        return cast(List[str], self.options.runtime_targets)
