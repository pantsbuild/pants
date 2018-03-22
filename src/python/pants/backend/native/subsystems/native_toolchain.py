# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

from pants.backend.native.subsystems.clang import Clang
from pants.backend.native.subsystems.gcc import GCC
from pants.backend.native.subsystems.platform_specific.linux.binutils import Binutils
from pants.binaries.execution_environment_mixin import ExecutionEnvironmentMixin
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.osutil import get_os_name, normalize_os_name


class NativeToolchain(Subsystem, ExecutionEnvironmentMixin):

  options_scope = 'native-toolchain'

  PLATFORM_SPECIFIC_TOOLCHAINS = {
    # TODO(cosmicexplorer): 'darwin' should have everything here, but there's no
    # open-source linker for OSX...yet.
    'darwin': [GCC, Clang],
    'linux': [GCC, Binutils, Clang],
  }

  @classmethod
  def _get_platform_specific_toolchains(cls):
    normed_os_name = normalize_os_name(get_os_name())
    return cls.PLATFORM_SPECIFIC_TOOLCHAINS[normed_os_name]

  @classmethod
  def subsystem_dependencies(cls):
    prev = super(NativeToolchain, cls).subsystem_dependencies()
    cur_platform_subsystems = cls._get_platform_specific_toolchains()
    return prev + tuple(sub.scoped(cls) for sub in cur_platform_subsystems)

  @memoized_property
  def _toolchain_instances(self):
    cur_platform_subsystems = self._get_platform_specific_toolchains()
    return [sub.scoped_instance(self) for sub in cur_platform_subsystems]

  def modify_environment(self, env):
    return self.apply_successive_env_modifications(env, self._toolchain_instances)
