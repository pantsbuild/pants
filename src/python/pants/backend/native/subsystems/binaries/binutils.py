# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import ExternalTool, ExternalToolError
from pants.engine.platform import Platform


class Binutils(ExternalTool):
    options_scope = "binutils"
    default_version = "2.30"
    default_known_versions = [
        "2.30|linux |7e78ee54d18fa8ad30c793e78aec24b9ddcc184a8aee5675f41d40bf6d0c89fe|40121937",
    ]

    def generate_url(self, plat: Platform) -> str:
        if plat != Platform.linux:
            raise ExternalToolError()
        return f"https://binaries.pantsbuild.org/bin/binutils/linux/x86_64/{self.options.version}/binutils.tar.gz"
