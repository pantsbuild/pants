# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.native.config.environment import Assembler, Linker
from pants.binaries.binary_tool import NativeTool
from pants.engine.rules import rule


class Binutils(NativeTool):
    options_scope = "binutils"
    default_version = "2.30"
    archive_type = "tgz"

    def path_entries(self):
        return [os.path.join(self.select(), "bin")]

    def assembler(self) -> Assembler:
        return Assembler(
            path_entries=self.path_entries(),
            exe_filename="as",
            runtime_library_dirs=(),
            extra_args=(),
        )

    def linker(self) -> Linker:
        return Linker(
            path_entries=self.path_entries(),
            exe_filename="ld",
            runtime_library_dirs=(),
            linking_library_dirs=(),
            extra_args=(),
            extra_object_files=(),
        )


@rule
def get_as(binutils: Binutils) -> Assembler:
    return binutils.assembler()


@rule
def get_ld(binutils: Binutils) -> Linker:
    return binutils.linker()


def create_binutils_rules():
    return [
        get_as,
        get_ld,
    ]
