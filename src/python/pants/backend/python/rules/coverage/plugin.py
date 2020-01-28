# coding=utf-8
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
import sys

from coverage import CoveragePlugin, FileTracer
from coverage.config import DEFAULT_PARTIAL, DEFAULT_PARTIAL_ALWAYS
from coverage.misc import join_regex
from coverage.parser import PythonParser
from coverage.python import PythonFileReporter, get_python_source


# NB: This file must keep Python 2 support because it is a resource that may be run with Python 2.


class SimpleFileTracer(FileTracer):
  def __init__(self, filename, relname, test_time):
    super(SimpleFileTracer, self).__init__()
    self._filename = filename
    self._relname = relname

  def source_filename(self):
    if self.test_time:
      return self.relname
    else:
      return self.filename


class SimpleFileReporter(PythonFileReporter):
  """Report support for a Python file."""

  def __init__(self, relative_source_root, source_root_stripped_filename, test_time, coverage=None):
    self.coverage = coverage
    self.relative_source_root = relative_source_root
    self.source_root_stripped_filename = source_root_stripped_filename
    self.filename_with_source_root = os.path.join(relative_source_root, source_root_stripped_filename)
    self.filename = source_root_stripped_filename
    self.test_time = test_time
    self._excluded = None

  def relative_filename(self):
    return self.filename_with_source_root

  _parser = None
  @property
  def parser(self):
    if self._parser is None:
      if self.test_time:
        self._parser = PythonParser(filename=self.filename)
      else:
        self._parser = PythonParser(filename=self.filename_with_source_root)

      self._parser.parse_source()
    return self._parser

  def no_branch_lines(self):
    return self.parser.lines_matching(
      join_regex(DEFAULT_PARTIAL[:]),
      join_regex(DEFAULT_PARTIAL_ALWAYS[:]),
    )

  _source = None
  def source(self):
    if self._source is None:
      if self.test_time:
        self._source = get_python_source(self.filename)
      else:
        self._source = get_python_source(self.filename_with_source_root)
    return self._source


class ChrootRemappingPlugin(CoveragePlugin):
  """A plugin that knows how to map Pants PEX chroots back to repo source code when reporting."""

  def __init__(self, src_chroot_path, src_to_target_base, test_time):
    super(ChrootRemappingPlugin, self).__init__()
    self._src_chroot_path = src_chroot_path
    self._src_to_target_base = src_to_target_base
    self.test_time = test_time

  def find_executable_files(self, top):
    # coverage uses this to associate files with this plugin.
    # We only want to be associated with the sources we know about.
    if top.startswith(self._src_chroot_path):
      for dirname, _, filenames in os.walk(top):
        reldir = os.path.relpath(dirname, self._src_chroot_path)
        for filename in filenames:
          if os.path.join(reldir, filename) in self._src_to_target_base:
            yield os.path.join(dirname, filename)

  def file_tracer(self, filename):
    # Note that coverage will only call this on files that we yielded from find_executable_files(),
    # so they should all pass this check anyway, but it doesn't hurt to check again.
    # Note also that you cannot exclude .py files from tracing or reporting by returning None here.
    # All that does is register this plugin's disinterest in the file, but coverage will still
    # trace and report it using the standard tracer and reporter.
    if filename.startswith(self._src_chroot_path):
      src = os.path.relpath(filename, self._src_chroot_path)
      target_base = self._src_to_target_base.get(src)
      if target_base is not None:
        return SimpleFileTracer(filename=os.path.join([target_base, src]), relname=src, test_time=self.test_time)

  def file_reporter(self, filename):
    src = os.path.relpath(filename, self._src_chroot_path)
    target_base = self._src_to_target_base.get(src)
    return SimpleFileReporter(relative_source_root=target_base, source_root_stripped_filename=src, test_time=self.test_time)


def coverage_init(reg, options):
  src_chroot_path = os.getcwd()
  src_to_target_base = json.loads(options['source_to_target_base'])
  test_time = json.loads(options['test_time'])
  reg.add_file_tracer(ChrootRemappingPlugin(src_chroot_path, src_to_target_base, test_time))
