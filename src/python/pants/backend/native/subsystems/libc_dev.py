# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.backend.native.config.environment import HostLibcDev
from pants.backend.native.subsystems.utils.parse_search_dirs import ParseSearchDirs
from pants.base.hash_utils import hash_file
from pants.option.custom_types import dir_option
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class LibcDev(Subsystem):
  """Subsystem to detect and provide the host's installed version of a libc "dev" package.

  A libc "dev" package is provided on most Linux systems by default, but may not be located at any
  standardized path. We define a libc dev package as one which provides crti.o, an object file which
  is part of any libc implementation and is required to create executables (more information
  available at https://wiki.osdev.org/Creating_a_C_Library).

  NB: This is currently unused except in CI, because we have no plans to support creating native
  executables from C or C++ sources yet (PRs welcome!). It is used to provide an "end-to-end" test
  of the compilation and linking toolchain in CI by creating and invoking a "hello world"
  executable.
  """

  options_scope = 'libc'

  class HostLibcDevResolutionError(Exception): pass

  @classmethod
  def subsystem_dependencies(cls):
    return super(LibcDev, cls).subsystem_dependencies() + (ParseSearchDirs.scoped(cls),)

  @memoized_property
  def _parse_search_dirs(self):
    return ParseSearchDirs.scoped_instance(self)

  @classmethod
  def register_options(cls, register):
    super(LibcDev, cls).register_options(register)

    register('--enable-libc-search', type=bool, default=False, fingerprint=True, advanced=True,
             help="Whether to search for the host's libc installation. Set to False if the host "
                  "does not have a libc install with crti.o -- this file is necessary to create "
                  "executables on Linux hosts.")
    register('--libc-dir', type=dir_option, default=None, fingerprint=True, advanced=True,
             help='A directory containing a host-specific crti.o from libc.')
    register('--host-compiler', type=str, default='gcc', fingerprint=True, advanced=True,
             help='The host compiler to invoke with -print-search-dirs to find the host libc.')

  # NB: crti.o is required to create executables on Linux. Our provided gcc and clang can find it if
  # the containing directory is within the LIBRARY_PATH environment variable when we invoke the
  # compiler.
  _LIBC_INIT_OBJECT_FILE = 'crti.o'

  def _get_host_libc_from_host_compiler(self):
    """Locate the host's libc-dev installation using a specified host compiler's search dirs."""
    compiler_exe = self.get_options().host_compiler

    # Implicitly, we are passing in the environment of the executing pants process to
    # `get_compiler_library_dirs()`.
    # These directories are checked to exist!
    library_dirs = self._parse_search_dirs.get_compiler_library_dirs(compiler_exe)

    libc_crti_object_file = None
    for libc_dir_candidate in library_dirs:
      maybe_libc_crti = os.path.join(libc_dir_candidate, self._LIBC_INIT_OBJECT_FILE)
      if os.path.isfile(maybe_libc_crti):
        libc_crti_object_file = maybe_libc_crti
        break

    if not libc_crti_object_file:
      raise self.HostLibcDevResolutionError(
        "Could not locate {fname} in library search dirs {dirs} from compiler: {compiler!r}. "
        "You may need to install a libc dev package for the current system. "
        "For many operating systems, this package is named 'libc-dev' or 'libc6-dev'."
        .format(fname=self._LIBC_INIT_OBJECT_FILE, dirs=library_dirs, compiler=compiler_exe))

    return HostLibcDev(crti_object=libc_crti_object_file,
                       fingerprint=hash_file(libc_crti_object_file))

  @memoized_property
  def _host_libc(self):
    """Use the --libc-dir option if provided, otherwise invoke a host compiler to find libc dev."""
    libc_dir_option = self.get_options().libc_dir
    if libc_dir_option:
      maybe_libc_crti = os.path.join(libc_dir_option, self._LIBC_INIT_OBJECT_FILE)
      if os.path.isfile(maybe_libc_crti):
        return HostLibcDev(crti_object=maybe_libc_crti,
                           fingerprint=hash_file(maybe_libc_crti))
      raise self.HostLibcDevResolutionError(
        "Could not locate {} in directory {} provided by the --libc-dir option."
        .format(self._LIBC_INIT_OBJECT_FILE, libc_dir_option))

    return self._get_host_libc_from_host_compiler()

  def get_libc_dirs(self, platform):
    if not self.get_options().enable_libc_search:
      return []

    return platform.resolve_platform_specific({
      'darwin': lambda: [],
      'linux': lambda: [self._host_libc.get_lib_dir()],
    })
