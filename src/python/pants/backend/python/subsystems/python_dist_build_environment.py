# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.binaries.execution_environment_mixin import ExecutionEnvironmentMixin
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class PythonDistBuildEnvironment(Subsystem, ExecutionEnvironmentMixin):

  options_scope = 'python-dist-build-environment'

  @classmethod
  def subsystem_dependencies(cls):
    return super(PythonDistBuildEnvironment, cls).subsystem_dependencies() + (NativeToolchain.scoped(cls),)

  @memoized_property
  def _native_toolchain(self):
    return NativeToolchain.scoped_instance(self)

  def modify_environment(self, env):
    env = self._native_toolchain.modify_environment(env)
    # If we're going to be wrapping setup.py-based projects, we really should be
    # doing it through a subclass of a distutils UnixCCompiler (in Lib/distutils
    # in the CPython source) instead of hoping setup.py knows what to do. The
    # default UnixCCompiler from distutils will build a 32/64-bit "fat binary"
    # unless you use their undocumented ARCHFLAGS env var, and there may be more
    # dragons later on.
    env['CC'] = 'gcc'
    env['CXX'] = 'g++'
    env['ARCHFLAGS'] = '-arch x86_64'
    return env
