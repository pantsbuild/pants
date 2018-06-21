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
from pants.util.strutil import create_path_env_var, safe_shlex_join


logger = logging.getLogger(__name__)


class ParseSearchDirs(Subsystem):

  options_scope = 'parse-search-dirs'

  class ParseSearchDirsError(Exception): pass

  @memoized_classproperty
  def _search_dirs_libraries_regex(cls):
    return re.compile('^libraries: =(.*)$', flags=re.MULTILINE)

  def _parse_libraries_from_compiler_search_dirs(self, compiler_exe, path_entries=None):
    # This argument is supported by at least gcc and clang.
    cmd = [compiler_exe, '-print-search-dirs']

    if not path_entries:
      path_entries = []

    try:
      # Get stderr interspersed in the error message too -- this should not affect output parsing.
      compiler_output = subprocess.check_output(
        cmd,
        env={'PATH': create_path_env_var(path_entries)},
        stderr=subprocess.STDOUT)
    except OSError as e:
      # We use `safe_shlex_join` here to pretty-print the command.
      raise self.ParseSearchDirsError(
        "Invocation of '{}' with argv {!r} failed."
        .format(compiler_exe, safe_shlex_join(cmd)),
        e)

    libs_line = self._search_dirs_libraries_regex.search(compiler_output)

    if not libs_line:
      raise self.ParseSearchDirsError(
        "Could not parse libraries from output of {!r}:\n{}"
        .format(safe_shlex_join(cmd), compiler_output))

    return libs_line.group(1).split(':')

  def get_compiler_library_dirs(self, compiler_exe, path_entries=None):
    all_dir_candidates = self._parse_libraries_from_compiler_search_dirs(
      compiler_exe,
      path_entries=path_entries)

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
