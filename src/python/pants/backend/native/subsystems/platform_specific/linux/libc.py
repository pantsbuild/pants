# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import re

from twitter.common.collections import OrderedSet

from pants.base.hash_utils import hash_file
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_readable_dir
from pants.util.memo import memoized_classproperty, memoized_property
from pants.util.objects import datatype
from pants.util.process_handler import subprocess
from pants.util.strutil import safe_shlex_join


logger = logging.getLogger(__name__)


# FIXME: make this an @rule, after we can automatically produce LibcDev (see #5788).
class HostLibcDev(datatype(['crti_object', 'fingerprint'])): pass


# TODO: think about how this could share any structure with XCodeCLITools, which is very similar in
# spirit.
class LibcDev(Subsystem):
  """Subsystem to detect and provide the host's installed version of a libc "dev" package.

  This subsystem exists to give a useful error message if the package isn't
  installed, and to allow a nonstandard install location.
  """

  options_scope = 'libc'

  class HostLibcDevResolutionError(Exception):

    def __init__(self, compiler, cmd, err_msg, *args, **kwargs):
      # We use `safe_shlex_join` here to pretty-print the command.
      msg = ("In command={cmd!r} with --host-compiler={compiler!r}: {err_msg}"
             .format(cmd=safe_shlex_join(cmd),
                     compiler=compiler,
                     err_msg=err_msg))
      super(LibcDev.HostLibcDevResolutionError, self).__init__(msg, *args, **kwargs)

  @classmethod
  def register_options(cls, register):
    super(LibcDev, cls).register_options(register)

    # TODO: make something in custom_types.py for "a path to an existing executable file (absolute
    # or relative to buildroot), or a filename that will be resolved against the PATH in some
    # subprocess".
    register('--host-compiler', type=str, default='gcc', advanced=True,
             help='The host compiler to invoke with -print-search-dirs to find the host libc.')

  @memoized_classproperty
  def _search_dirs_libraries_regex(cls):
    return re.compile('^libraries: =(.*)$', flags=re.MULTILINE)

  def _parse_libraries_from_compiler_search_dirs(self, compiler_exe):
    # This argument is supported by at least gcc and clang.
    cmd = [compiler_exe, '-print-search-dirs']

    try:
      # Get stderr interspersed in the error message too -- this should not affect output parsing.
      compiler_output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except OSError as e:
      raise self.HostLibcDevResolutionError(compiler_exe, cmd, "invocation failed.", e)

    libs_line = self._search_dirs_libraries_regex.search(compiler_output)

    if not libs_line:
      raise self.HostLibcDevResolutionError(
        compiler_exe, cmd,
        "Could not parse libraries from output:\n{}".format(compiler_output))

    return cmd, libs_line.group(1).split(':')

  # NB: crti.o is required to create executables on Linux. Our provided gcc can find it if the
  # containing directory is within the LIBRARY_PATH environment variable when we invoke gcc.
  # Note that clang is not able to use LIBRARY_PATH to find this file -- instead, you need to set
  # --sysroot and provide a -Bprefix (may require a space?) such that this file is located at
  # <sysroot>/<prefix>/lib/crti.o. Setting --sysroot requires adding so many more "-Bprefix"
  # arguments to add other required files and libraries for linking that we do not try to link with
  # clang at all currently.
  _LIBC_INIT_OBJECT_FILE = 'crti.o'

  @memoized_property
  def host_libc(self):
    """Locate the host's libc-dev installation using a specified host compiler's search dirs."""
    compiler_exe = self.get_options().host_compiler

    # We use `cmd` for error messages below.
    cmd, compiler_search_libraries = self._parse_libraries_from_compiler_search_dirs(compiler_exe)

    real_lib_dirs = OrderedSet()

    for lib_dir_path in compiler_search_libraries:
      # Could use a `seen_dir_paths` set if we want to avoid pinging the fs for duplicate entries.
      if is_readable_dir(lib_dir_path):
        real_lib_dirs.add(os.path.realpath(lib_dir_path))
      else:
        logger.debug("non-existent or non-accessible program directory at {} while locating libc."
                     .format(lib_dir_path))

    libc_crti_object_file = None
    for libc_dir_candidate in real_lib_dirs:
      maybe_libc_crti = os.path.join(libc_dir_candidate, self._LIBC_INIT_OBJECT_FILE)
      if os.path.isfile(maybe_libc_crti):
        libc_crti_object_file = maybe_libc_crti
        break

    if not libc_crti_object_file:
      raise self.HostLibcDevResolutionError(
        compiler_exe, cmd,
        "Could not locate {fname} in library search dirs {dirs}. "
        "You may need to install a libc dev package for the current system. "
        "For many operating systems, this package is named 'libc-dev' or 'libc6-dev'."
        .format(fname=self._LIBC_INIT_OBJECT_FILE, dirs=real_lib_dirs))

    return HostLibcDev(crti_object=libc_crti_object_file,
                       fingerpint=hash_file(libc_crti_object_file))
