# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Support for using C and C++ with Python distributions via `ctypes`."""

from pants.backend.native.subsystems.binaries.binutils import create_binutils_rules
from pants.backend.native.subsystems.binaries.gcc import create_gcc_rules
from pants.backend.native.subsystems.binaries.llvm import create_llvm_rules
from pants.backend.native.subsystems.native_toolchain import create_native_toolchain_rules
from pants.backend.native.subsystems.xcode_cli_tools import create_xcode_cli_tools_rules


def rules():
    return (
        *create_native_toolchain_rules(),
        *create_xcode_cli_tools_rules(),
        *create_binutils_rules(),
        *create_gcc_rules(),
        *create_llvm_rules(),
    )
