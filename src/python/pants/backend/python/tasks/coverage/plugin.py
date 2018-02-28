# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os

from coverage import CoveragePlugin, FileTracer
from coverage.config import DEFAULT_PARTIAL, DEFAULT_PARTIAL_ALWAYS
from coverage.misc import join_regex
from coverage.parser import PythonParser
from coverage.python import PythonFileReporter


class MyFileTracer(FileTracer):
  def __init__(self, filename):
    super(MyFileTracer, self).__init__()
    self._filename = filename

  def source_filename(self):
    return self._filename


class MyFileReporter(PythonFileReporter):
  """A python file reporter that knows how to map Pants PEX chroots back to repo source code."""

  def __init__(self, morf, relpath):
    super(MyFileReporter, self).__init__(morf, coverage=None)
    self._relpath = relpath

  def relative_filename(self):
    return self._relpath

  # TODO(John Sirois): Kill the workaround overrides below if there is a useable upstream
  # resolution to:
  #   https://bitbucket.org/ned/coveragepy/issues/646/modifying-coverage-reporting-for-python

  @property
  def parser(self):
    if self._parser is None:
      self._parser = PythonParser(filename=self.filename)
      self._parser.parse_source()
    return self._parser

  def no_branch_lines(self):
    return self.parser.lines_matching(join_regex(DEFAULT_PARTIAL[:]),
                                      join_regex(DEFAULT_PARTIAL_ALWAYS[:]))


class MyPlugin(CoveragePlugin):
  """A plugin that knows how to map Pants PEX chroots back to repo source code when reporting."""

  def __init__(self, buildroot, src_to_chroot):
    super(MyPlugin, self).__init__()
    self._buildroot = buildroot
    self._src_to_chroot = src_to_chroot

  def find_executable_files(self, top):
    for chroot_path in self._src_to_chroot.values():
      if top.startswith(chroot_path):
        for root, _, files in os.walk(top):
          for f in files:
            if f.endswith('.py'):
              yield os.path.join(root, f)
        break

  def file_tracer(self, filename):
    for chroot_path in self._src_to_chroot.values():
      if filename.startswith(chroot_path):
        return MyFileTracer(filename)

  def file_reporter(self, filename):
    src_file = self._map_to_src(filename)
    mapped_relpath = os.path.relpath(src_file, self._buildroot)
    return MyFileReporter(filename, mapped_relpath)

  def _map_to_src(self, chroot):
    for src_dir, chroot_dir in self._src_to_chroot.items():
      if chroot.startswith(chroot_dir):
        return src_dir + chroot[len(chroot_dir):]
    raise AssertionError('Failed to map traced file {} to any source root via '
                         'source root -> chroot mappings:\n\t{}'
                         .format(chroot, '\n\t'.join(sorted('{} -> {}'.format(src_dir, chroot_dir)
                                                            for src_dir, chroot_dir
                                                            in self._src_to_chroot.items()))))


def coverage_init(reg, options):
  buildroot = options['buildroot']
  src_to_chroot = json.loads(options['src_to_chroot'])
  reg.add_file_tracer(MyPlugin(buildroot, src_to_chroot))
