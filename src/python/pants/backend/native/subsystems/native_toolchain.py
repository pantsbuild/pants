# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.native.config.environment import CCompiler, CppCompiler, HostLibcDevInstallation, Linker, Platform
from pants.backend.native.subsystems.binaries.binutils import Binutils
from pants.backend.native.subsystems.glibc import GLibc
from pants.backend.native.subsystems.binaries.gcc import GCC
from pants.backend.native.subsystems.binaries.llvm import LLVM
from pants.backend.native.subsystems.xcode_cli_tools import XCodeCLITools
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Select
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.objects import datatype
from pants.util.osutil import get_normalized_os_name


class NativeToolchain(Subsystem):
  """Abstraction over platform-specific tools to compile and link native code.

  When this subsystem is consumed, Pants will download and unpack archives (if necessary) which
  together provide an appropriate "native toolchain" for the host platform: a compiler and linker,
  usually. This subsystem exposes the toolchain through `@rule`s, which tasks then request during
  setup or execution (synchronously, for now).

  NB: Currently, on OSX, Pants will find and invoke the XCode command-line tools, or error out with
  installation instructions if the XCode tools could not be found.
  """

  options_scope = 'native-toolchain'

  @classmethod
  def subsystem_dependencies(cls):
    return super(NativeToolchain, cls).subsystem_dependencies() + (
      Binutils.scoped(cls),
      GCC.scoped(cls),
      GLibc.scoped(cls),
      LLVM.scoped(cls),
      XCodeCLITools.scoped(cls),
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

  @memoized_property
  def _xcode_cli_tools(self):
    return XCodeCLITools.scoped_instance(self)

  @memoized_property
  def _libc(self):
    return GLibc.scoped_instance(self)


@rule(Linker, [Select(Platform), Select(NativeToolchain)])
def select_linker(platform, native_toolchain):
  # TODO(#5933): make it possible to yield Get with a non-static
  # subject type and use `platform.resolve_platform_specific()`, something like:
  # linker = platform.resolve_platform_specific({
  #   'darwin': lambda: Get(Linker, XCodeCLITools, native_toolchain._xcode_cli_tools),
  #   'linux': lambda: Get(Linker, Binutils, native_toolchain._binutils),
  # })
  if platform.normalized_os_name == 'darwin':
    # TODO(#5663): turn this into LLVM when lld works.
    linker = yield Get(Linker, XCodeCLITools, native_toolchain._xcode_cli_tools)
  else:
    linker = yield Get(Linker, Binutils, native_toolchain._binutils)
  yield linker


@rule(CCompiler, [Select(Platform), Select(NativeToolchain)])
def select_c_compiler(platform, native_toolchain):
  if platform.normalized_os_name == 'darwin':
    c_compiler = yield Get(CCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
  else:
    c_compiler = yield Get(CCompiler, GCC, native_toolchain._gcc)
  yield c_compiler


@rule(CppCompiler, [Select(Platform), Select(NativeToolchain)])
def select_cpp_compiler(platform, native_toolchain):
  if platform.normalized_os_name == 'darwin':
    cpp_compiler = yield Get(CppCompiler, XCodeCLITools, native_toolchain._xcode_cli_tools)
  else:
    cpp_compiler = yield Get(CppCompiler, GCC, native_toolchain._gcc)
  yield cpp_compiler


@rule(HostLibcDevInstallation, [Select(Platform), Select(NativeToolchain)])
def select_libc_dev_install(platform, native_toolchain):
  lib_dir = platform.resolve_platform_specific({
    'darwin': lambda: None,
    'linux': lambda: native_toolchain._libc.lib_dir(),
  })

  yield HostLibcDevInstallation(lib_dir=lib_dir)


def create_native_toolchain_rules():
  return [
    select_linker,
    select_c_compiler,
    select_cpp_compiler,
    select_libc_dev_install,
    RootRule(NativeToolchain),
  ]
