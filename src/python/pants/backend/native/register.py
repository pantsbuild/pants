# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Support for using C and C++ with Python distributions via `ctypes`."""

from pants.backend.native.rules.targets import (
    CLibrary,
    ConanNativeLibrary,
    CppLibrary,
    PackagedNativeLibrary,
)
from pants.backend.native.subsystems.binaries.binutils import create_binutils_rules
from pants.backend.native.subsystems.binaries.gcc import create_gcc_rules
from pants.backend.native.subsystems.binaries.llvm import create_llvm_rules
from pants.backend.native.subsystems.native_build_settings import NativeBuildSettings
from pants.backend.native.subsystems.native_toolchain import create_native_toolchain_rules
from pants.backend.native.subsystems.xcode_cli_tools import create_xcode_cli_tools_rules
from pants.backend.native.targets.external_native_library import ConanRequirement
from pants.backend.native.targets.external_native_library import (
    ExternalNativeLibrary as ExternalNativeLibraryV1,
)
from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.backend.native.targets.native_library import CLibrary as CLibraryV1
from pants.backend.native.targets.native_library import CppLibrary as CppLibraryV1
from pants.backend.native.targets.packaged_native_library import (
    PackagedNativeLibrary as PackagedNativeLibraryV1,
)
from pants.backend.native.tasks.c_compile import CCompile
from pants.backend.native.tasks.conan_fetch import ConanFetch
from pants.backend.native.tasks.conan_prep import ConanPrep
from pants.backend.native.tasks.cpp_compile import CppCompile
from pants.backend.native.tasks.link_shared_libraries import LinkSharedLibraries
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(
        targets={
            CLibraryV1.alias(): CLibraryV1,
            CppLibraryV1.alias(): CppLibraryV1,
            ExternalNativeLibraryV1.alias(): ExternalNativeLibraryV1,
            PackagedNativeLibraryV1.alias(): PackagedNativeLibraryV1,
        },
        objects={
            ConanRequirement.alias(): ConanRequirement,
            NativeArtifact.alias(): NativeArtifact,
        },
    )


def global_subsystems():
    return {NativeBuildSettings}


def register_goals():
    # TODO(#5962): register these under the 'compile' goal when we eliminate the product transitive
    # dependency from export -> compile.
    task(name="conan-prep", action=ConanPrep).install("native-compile")
    task(name="conan-fetch", action=ConanFetch).install("native-compile")
    task(name="c-for-ctypes", action=CCompile).install("native-compile")
    task(name="cpp-for-ctypes", action=CppCompile).install("native-compile")
    task(name="shared-libraries", action=LinkSharedLibraries).install("link")


def rules():
    return (
        *create_native_toolchain_rules(),
        *create_xcode_cli_tools_rules(),
        *create_binutils_rules(),
        *create_gcc_rules(),
        *create_llvm_rules(),
    )


def targets2():
    return [CLibrary, CppLibrary, ConanNativeLibrary, PackagedNativeLibrary]
