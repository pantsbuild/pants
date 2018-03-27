# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

from pants.backend.native.subsystems.gcc import GCC
from pants.backend.native.subsystems.platform_specific.darwin.xcode_cli_tools import XCodeCLITools
from pants.backend.native.subsystems.platform_specific.linux.binutils import Binutils
from pants.binaries.binary_tool import ExecutablePathProvider
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method, memoized_property
from pants.util.osutil import get_os_name, normalize_os_name


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
  _CROSS_PLATFORM_SUBSYSTEMS = [GCC]

  # This is a map of {<platform> -> [<subsystem_cls>, ...]}; the key is the
  # normalized OS name, and the value is a list of subsystem class objects that
  # implement `ExecutablePathProvider`. The native toolchain subsystem will
  # declare dependencies only on the subsystems for the platform Pants is
  # executing on.
  _PLATFORM_SPECIFIC_SUBSYSTEMS = {
    'darwin': [XCodeCLITools],
    'linux': [Binutils],
  }

  class UnsupportedPlatformError(Exception): pass

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

    # NB: path entries for platform-specific subsystems currently take
    # precedence over cross-platform ones -- this could be made configurable.
    all_subsystems_for_toolchain = subsystems_for_host + cls._CROSS_PLATFORM_SUBSYSTEMS

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

  def path_entries(self):
    """Note how it adds these in order, and how we can't necessarily expect /bin
    and /usr/bin to be on the user's PATH when they invoke Pants!"""
    entries = []
    for subsystem in self._subsystem_instances:
      entries.extend(subsystem.path_entries())

    return entries
