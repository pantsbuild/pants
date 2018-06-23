# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import re

from twitter.common.collections import OrderedSet

from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_readable_dir
from pants.util.memo import memoized_classproperty
from pants.util.process_handler import subprocess
from pants.util.strutil import safe_shlex_join


logger = logging.getLogger(__name__)


class ParseSearchDirs(Subsystem):
  """Parse the output of invoking a compiler with the '-print-search-dirs' argument for lib dirs.

  This is used to expose resources from one compiler (e.g. a compiler preinstalled on the host which
  has knowledge of distro-maintained system libraries such as libc) to the compilers/linkers that
  Pants provides. This is also used to share resources between different :class:`BinaryTool`s with
  compiler executables.
  """

  options_scope = 'parse-search-dirs'

  class ParseSearchDirsError(Exception): pass

  @memoized_classproperty
  def _search_dirs_libraries_regex(cls):
    return re.compile('^libraries: =(.*)$', flags=re.MULTILINE)

  def _parse_libraries_from_compiler_search_dirs(self, compiler_exe, env):
    # This argument is supported by at least gcc and clang.
    cmd = [compiler_exe, '-print-search-dirs']

    try:
      # Get stderr interspersed in the error message too -- this should not affect output parsing.
      compiler_output = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT)
    except OSError as e:
      # We use `safe_shlex_join` here to pretty-print the command.
      raise self.ParseSearchDirsError(
        "Invocation of '{}' with argv {!r} failed."
        .format(compiler_exe, safe_shlex_join(cmd)),
        e)
    except subprocess.CalledProcessError as e:
      raise self.ParseSearchDirsError(
        "Invocation of '{}' with argv {!r} exited with non-zero code {}. output:\n{}"
        .format(compiler_exe, safe_shlex_join(cmd), e.returncode, e.output),
        e)

    libs_line = self._search_dirs_libraries_regex.search(compiler_output)

    if not libs_line:
      raise self.ParseSearchDirsError(
        "Could not parse libraries from output of {!r}:\n{}"
        .format(safe_shlex_join(cmd), compiler_output))

    return libs_line.group(1).split(':')

  def get_compiler_library_dirs(self, compiler_exe, env=None):
    all_dir_candidates = self._parse_libraries_from_compiler_search_dirs(compiler_exe, env=env)

    real_lib_dirs = OrderedSet()

    for lib_dir_path in all_dir_candidates:
      # Could use a `seen_dir_paths` set if we want to avoid pinging the fs for duplicate entries.
      if is_readable_dir(lib_dir_path):
        real_lib_dirs.add(os.path.realpath(lib_dir_path))
      else:
        logger.debug("non-existent or non-accessible program directory at {} while "
                     "parsing libraries from {}"
                     .format(lib_dir_path, compiler_exe))

    return list(real_lib_dirs)
