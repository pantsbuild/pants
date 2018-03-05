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


class SimpleFileTracer(FileTracer):
  def __init__(self, filename):
    super(SimpleFileTracer, self).__init__()
    self._filename = filename

  def source_filename(self):
    return self._filename


class SimpleFileReporter(PythonFileReporter):
  def __init__(self, morf, relpath):
    super(SimpleFileReporter, self).__init__(morf, coverage=None)
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


class ChrootRemappingPlugin(CoveragePlugin):
  """A plugin that knows how to map Pants PEX chroots back to repo source code when reporting."""

  def __init__(self, buildroot, src_chroot_path, src_to_target_base):
    super(ChrootRemappingPlugin, self).__init__()
    self._buildroot = buildroot
    self._src_chroot_path = src_chroot_path
    self._src_to_target_base = src_to_target_base
    self._target_bases = set(self._src_to_target_base.values())

  def find_executable_files(self, top):
    if top.startswith(self._src_chroot_path):
      for root, dirs, files in os.walk(top):
        for f in files:
          if f.endswith('.py'):
            yield os.path.join(root, f)

  def file_tracer(self, filename):
    # Don't trace third party libraries or the standard lib, just user code in the src chroot.
    if filename.startswith(self._src_chroot_path):
      src = os.path.relpath(filename, self._src_chroot_path)
      if src in self._src_to_target_base:
        return SimpleFileTracer(filename)

  def file_reporter(self, filename):
    mapped_relpath = self._map_relpath(filename)
    return SimpleFileReporter(filename, mapped_relpath)

  def _map_relpath(self, filename):
    src = os.path.relpath(filename, self._src_chroot_path)
    target_base = self._src_to_target_base.get(src) or self._find_target_base(src)
    return os.path.join(target_base, src) if target_base else filename

  def _find_target_base(self, src):
    for target_base in self._target_bases:
      if os.path.isfile(os.path.join(self._buildroot, target_base, src)):
        return target_base


def coverage_init(reg, options):
  buildroot = options['buildroot']
  src_chroot_path = options['src_chroot_path']
  src_to_target_base = json.loads(options['src_to_target_base'])
  reg.add_file_tracer(ChrootRemappingPlugin(buildroot, src_chroot_path, src_to_target_base))
