# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.native.config.environment import CCompiler, CppCompiler, Linker, Platform
from pants.backend.native.subsystems.binaries.binutils import Binutils
from pants.backend.native.subsystems.binaries.gcc import GCC
from pants.backend.native.subsystems.binaries.llvm import LLVM
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Select
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class NativeToolchain(Subsystem):
  """Abstraction over platform-specific tools to compile and link native code.

  This "native toolchain" subsystem is an abstraction that exposes directories
  containing executables to compile and link "native" code (for now, C and C++
  are supported). Consumers of this subsystem can add these directories to their
  PATH to invoke subprocesses which use these tools.

  This abstraction is necessary for two reasons. First, because there are
  multiple binaries involved in compilation and linking, which often invoke
  other binaries that must also be available on the PATH. Second, because unlike
  other binary tools in Pants, we can't provide the same package built for both
  OSX and Linux, because there is no open-source linker for OSX with a
  compatible license.

  So when this subsystem is consumed, Pants will download and unpack archives
  (if necessary) which together provide an appropriate "native toolchain" for
  the host platform. On OSX, Pants will also find and provide path entries for
  the XCode command-line tools, or error out with installation instructions if
  the XCode tools could not be found.
  """

  options_scope = 'native-toolchain'

  # This is a list of subsystems which implement `ExecutablePathProvider` and
  # can be provided for all supported platforms.
  _CROSS_PLATFORM_SUBSYSTEMS = [LLVM, GCC]

  @classmethod
  def subsystem_dependencies(cls):
    return super(NativeToolchain, cls).subsystem_dependencies() + (
      Binutils.scoped(cls),
      GCC.scoped(cls),
      LLVM.scoped(cls),
    )

  @memoized_property
  def _binutils(self):
    return Binutils.scoped_instance(self)

  @memoized_property
  def _gcc(self):
    return GCC.scoped_instance(self)

  @memoized_property
  def _llvm(self):
    return LLVM.scoped_instance(self)


@rule(Linker, [Select(Platform), Select(NativeToolchain)])
def select_linker(platform, native_toolchain):
  # TODO(cosmicexplorer): make it possible to yield Get with a non-static
  # subject type and use `platform.resolve_platform_specific()`.
  if platform.normed_os_name == 'darwin':
    linker = yield Get(Linker, LLVM, native_toolchain._llvm)
  else:
    linker = yield Get(Linker, Binutils, native_toolchain._binutils)
  yield linker


@rule(CCompiler, [Select(NativeToolchain)])
def select_c_compiler(native_toolchain):
  c_compiler = yield Get(CCompiler, LLVM, native_toolchain._llvm)
  yield c_compiler


@rule(CppCompiler, [Select(NativeToolchain)])
def select_cpp_compiler(native_toolchain):
  cpp_compiler = yield Get(CppCompiler, LLVM, native_toolchain._llvm)
  yield cpp_compiler


def create_native_toolchain_rules():
  return [
    select_linker,
    select_c_compiler,
    select_cpp_compiler,
    RootRule(NativeToolchain),
  ]
