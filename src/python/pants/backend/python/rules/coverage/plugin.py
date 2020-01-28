# coding=utf-8
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import sys

from coverage import CoveragePlugin, FileTracer
from coverage.config import DEFAULT_PARTIAL, DEFAULT_PARTIAL_ALWAYS
from coverage.misc import join_regex
from coverage.parser import PythonParser
from coverage.python import PythonFileReporter, get_python_source


# TODO(Tansy): Document the insanity. coverage is loading these classes from class name strings stored in its database.


class PantsPythonFileReporter(PythonFileReporter):
  """Report support for a Python file."""

  def __init__(self, relative_source_root, source_root_stripped_filename, test_time, coverage=None):
    # TODO(tansy): Note why calling super on this class will break all the things.
    self.coverage = coverage
    self.filename_with_source_root = os.path.join(relative_source_root, source_root_stripped_filename)
    self.filename = source_root_stripped_filename
    self.test_time = test_time

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
      self._source = get_python_source(self.filename_with_source_root)
    return self._source


class SourceRootRemappingPlugin(CoveragePlugin):
  """A plugin that knows how to map the source root stripped sources used in tests back to sources with source
  roots for reporting."""

  def __init__(self, src_chroot_path, src_to_target_base, test_time):
    super().__init__()
    self._src_chroot_path = src_chroot_path
    self._src_to_target_base = src_to_target_base
    self.test_time = test_time

  def find_executable_files(self, top: str):
    # Coverage uses this to associate files with this plugin. We only want to be associated with the sources we
    # know about.
    if top.startswith(self._src_chroot_path):
      for dirname, _, filenames in os.walk(top):
        reldir = os.path.relpath(dirname, self._src_chroot_path)
        for filename in filenames:
          if os.path.join(reldir, filename) in self._src_to_target_base:
            yield os.path.join(dirname, filename)

  def file_reporter(self, filename: str):
    src = os.path.relpath(filename, self._src_chroot_path)
    target_base = self._src_to_target_base.get(src)
    return PantsPythonFileReporter(relative_source_root=target_base, source_root_stripped_filename=src, test_time=self.test_time)


def coverage_init(reg, options):
  src_chroot_path = os.getcwd()
  src_to_target_base = json.loads(options['source_to_target_base'])
  test_time = json.loads(options['test_time'])
  reg.add_file_tracer(SourceRootRemappingPlugin(src_chroot_path, src_to_target_base, test_time))
