# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.backend.native.subsystems.clang import Clang
from pants.backend.native.subsystems.gcc import GCC
from pants.backend.native.subsystems.platform_specific.darwin.xcode_cli_tools import XCodeCLITools
from pants.backend.native.subsystems.platform_specific.linux.binutils import Binutils
from pants.binaries.binary_tool import ExecutablePathProvider
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import environment_as, get_modified_path, temporary_dir
from pants.util.memo import memoized_method, memoized_property
from pants.util.osutil import get_os_name, normalize_os_name
from pants.util.process_handler import subprocess


logger = logging.getLogger(__name__)


_HELLO_WORLD_C = """
#include "stdio.h"

int main() {
  printf("%s\\n", "hello, world!");
}
"""


_HELLO_WORLD_CPP = """
#include <iostream>

int main() {
  std::cout << "hello, world!" << std::endl;
}
"""


class NativeToolchain(Subsystem, ExecutablePathProvider):
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
  the host platform. On OSX, Pants will find and provide path entries for the
  XCode command-line tools, or error out with installation instructions if the
  XCode tools could not be found.
  """

  options_scope = 'native-toolchain'

  # This is a list of subsystems which implement `ExecutablePathProvider` and
  # can be provided for all supported platforms.
  # TODO(cosmicexplorer): We should be adding Clang to this list, but we need to
  # merge all these tools under a single prefix (shared bin/, lib/, etc) in
  # order to work (add issue link here!!). For now we can separately add gcc and
  # binutils's bin/ dirs to separate components of the PATH, but this isn't a
  # working solution.
  _CROSS_PLATFORM_SUBSYSTEMS = [GCC, Clang]

  # This is a map of {<platform> -> [<subsystem_cls>, ...]}; the key is the
  # normalized OS name, and the value is a list of subsystem class objects that
  # implement `ExecutablePathProvider`. The native toolchain subsystem will
  # declare dependencies only on the subsystems for the platform Pants is
  # executing on.
  _PLATFORM_SPECIFIC_SUBSYSTEMS = {
    'darwin': [XCodeCLITools],
    'linux': [Binutils],
  }

  class UnsupportedPlatformError(Exception):
    """???"""

  class NativeToolchainConfigurationError(Exception):
    """???"""

  @classmethod
  @memoized_method
  def _get_platform_specific_subsystems(cls):
    os_name = get_os_name()
    normed_os_name = normalize_os_name(os_name)

    subsystems_for_host = cls._PLATFORM_SPECIFIC_SUBSYSTEMS.get(normed_os_name, None)

    if subsystems_for_host is None:
      raise cls.UnsupportedPlatformError(
        "Pants doesn't support building native code on this platform "
        "(uname: '{}').".format(os_name))

    # NB: path entries for cross-platform subsystems currently take precedence
    # over platform-specific ones -- this could be made configurable.
    all_subsystems_for_toolchain = cls._CROSS_PLATFORM_SUBSYSTEMS + subsystems_for_host

    return all_subsystems_for_toolchain

  @classmethod
  def subsystem_dependencies(cls):
    prev = super(NativeToolchain, cls).subsystem_dependencies()
    cur_platform_subsystems = cls._get_platform_specific_subsystems()
    return prev + tuple(sub.scoped(cls) for sub in cur_platform_subsystems)

  @memoized_property
  def _subsystem_instances(self):
    cur_platform_subsystems = self._get_platform_specific_subsystems()
    return [sub.scoped_instance(self) for sub in cur_platform_subsystems]

  def _invoke_capturing_output(self, cmd, cwd):
    logger.debug("invoking in cwd='{}', cmd='{}'".format(cwd, cmd))
    try:
      return subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
      raise NativeToolchainConfigurationError(
        "Command failed while configuring the native toolchain "
        "with code '{}', cwd='{}', cmd='{}'. Combined stdout and stderr:\n{}"
        .format(e.returncode, cwd, ' '.join(cmd), e.output),
        e)

  def _sanity_test(self, path_entries):
    """Try to compile and run a hello world program. Test all supported native
    languages."""

    logger.debug("invoking native toolchain sanity test with path_entries='{}'"
                 .format(path_entries))

    # TODO: show output here if the command fails!
    isolated_toolchain_path = ':'.join(path_entries)
    with environment_as(PATH=isolated_toolchain_path):
      with temporary_dir() as tmpdir:

        hello_c_path = os.path.join(tmpdir, 'hello.c')
        with open(hello_c_path, 'w') as hello_c:
          hello_c.write(_HELLO_WORLD_C)

        self._invoke_capturing_output(['cc', 'hello.c', '-o', 'hello_c'],
                                      cwd=tmpdir)
        c_output = self._invoke_capturing_output(['./hello_c'], cwd=tmpdir)
        if c_output != 'hello, world!\n':
          raise self.NativeToolchainConfigurationError("C sanity test failure!")

        hello_cpp_path = os.path.join(tmpdir, 'hello.cpp')
        with open(hello_cpp_path, 'w') as hello_cpp:
          hello_cpp.write(_HELLO_WORLD_CPP)

        self._invoke_capturing_output(['c++', 'hello.cpp', '-o', 'hello_cpp'],
                                      cwd=tmpdir)
        cpp_output = self._invoke_capturing_output(['./hello_cpp'], cwd=tmpdir)
        if cpp_output != 'hello, world!\n':
          raise self.NativeToolchainConfigurationError("C++ sanity test failure!")

  def path_entries(self):
    """Note how it adds these in order, and how we can't necessarily expect /bin
    and /usr/bin to be on the user's PATH when they invoke Pants!"""
    combined_path_entries = []
    for subsystem in self._subsystem_instances:
      combined_path_entries.extend(subsystem.path_entries())

    self._sanity_test(combined_path_entries)

    return combined_path_entries
