# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from hashlib import sha1

from pants.backend.native.subsystems.platform_specific.linux.binutils import Binutils
from pants.base.hash_utils import hash_file
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_executable, split_basename_and_dirname
from pants.util.memo import memoized_classproperty, memoized_property
from pants.util.objects import datatype
from pants.util.process_handler import subprocess


class HostLibc(datatype(['libc_dir', 'fingerprint'])): pass


# TODO: think about how this could share any structure with XCodeCLITools, which is very similar in
# spirit.
class Libc(Subsystem):
  """Subsystem to detect and provide the host's installed version of a libc "dev" package.

  This subsystem exists to give a useful error message if the package isn't
  installed, and to allow a nonstandard install location.
  """

  options_scope = 'libc'

  class HostLibcResolutionError(Exception): pass

  @classmethod
  def subsystem_dependencies(cls):
    return super(Libc, cls).subsystem_dependencies() + (Binutils.scoped(cls),)

  @memoized_property
  def _binutils(self):
    return Binutils.scoped_instance(self)

  @memoized_property
  def _ld_path(self):
    return os.path.join(self._binutils.select(), 'bin', 'ld')

  # NB: libc.so.6 is used on linux x86_64, see https://en.wikipedia.org/wiki/GNU_C_Library. The
  # containing directory should be provided in the LD_LIBRARY_PATH when invoking a linker.
  _LIBC_SO_NAME = 'libc.so.6'

  @memoized_classproperty
  def _libc_so_ldd_output_regex(cls):
    return re.compile('^\s+{soname} => (.*?{soname}) '.format(soname=re.escape(cls._LIBC_SO_NAME)),
                      flags=re.MULTILINE)

  @classmethod
  def _parse_libc_ldd_output(cls, ldd_out):
    libc_line = cls._libc_so_ldd_output_regex.search(ldd_out)

    if not libc_line:
      raise cls.HostLibcResolutionError("???")

    return libc_line.group(1)

  # NB: this file is required to create executables. gcc can find it if the containing directory is
  # within the LIBRARY_PATH environment variable.
  _EXECUTABLE_MAIN_REQUIRED_OBJECT_FILE = 'crti.o'

  @classmethod
  def _required_files(cls):
    return [cls._LIBC_SO_NAME, cls._EXECUTABLE_MAIN_REQUIRED_OBJECT_FILE]

  @memoized_property
  def host_libc(self):
    try:
      # TODO: why does this work?
      ldd_out = subprocess.check_output(['ldd', self._ld_path])
    except OSError as e:
      raise self.HostLibcResolutionError("???: {}".format(e))

    libc_so_path = self._parse_libc_ldd_output(ldd_out)

    if not is_executable(libc_so_path):
      raise self.HostLibcResolutionError("???")

    libc_dir, libc_so_name = split_basename_and_dirname(libc_so_path)

    # TODO: this check may be unnecessary.
    if libc_so_name != self._LIBC_SO_NAME:
      raise self.HostLibcResolutionError("???")

    hasher = sha1()

    # FIXME: we should be taking a hash of the file contents as well! we can share this with
    # XCodeCLITools!
    for fname in self._required_files():
      libc_file_path = os.path.join(libc_dir, fname)
      if not os.path.isfile(libc_file_path):
        raise self.HostLibcResolutionError("???")
      hash_file(libc_file_path, digest=hasher)

    return HostLibc(libc_dir, hasher.hexdigest())
