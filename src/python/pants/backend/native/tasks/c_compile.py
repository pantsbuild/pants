# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.native.subsystems.native_build_step import CCompileSettings
from pants.backend.native.targets.native_library import CLibrary
from pants.backend.native.tasks.native_compile import NativeCompile
from pants.util.objects import SubclassesOf


class CCompile(NativeCompile):

    options_scope = "c-compile"

    # Compile only C library targets.
    source_target_constraint = SubclassesOf(CLibrary)

    workunit_label = "c-compile"

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("CCompile", 0)]

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (CCompileSettings.scoped(cls),)

    def get_compile_settings(self):
        return CCompileSettings.scoped_instance(self)

    def get_compiler(self, native_library_target):
        return self.get_c_toolchain_variant(native_library_target).c_compiler
