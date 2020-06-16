# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os

from coverage import CoveragePlugin
from coverage.config import DEFAULT_PARTIAL, DEFAULT_PARTIAL_ALWAYS
from coverage.misc import join_regex
from coverage.parser import PythonParser
from coverage.python import PythonFileReporter, get_python_source


# Note: This plugin will appear to do nothing at all at test time. This is the correct behavior.
# The *only* thing coverage does with this plugin at test time is storing the class name in its
# SQL data (see the `tracer` table) eg: `__pants_coverage_plugin__.ChrootRemappingPlugin`.
#
# It will then hot load this plugin from the class name string in its SQL data when
# generate_coverage_report is run. If this data is missing, this plugin will not be used at report
# time, meaning the reports will fail to be generated as coverage will go looking for `foo/bar.py`
# instead of `src/python/foo/bar.py`.


class PantsPythonFileReporter(PythonFileReporter):
  """Report support for a Python file.

  At test time, we run coverage in an environment where all source roots have been stripped from
  source files. When we read the coverage report, we would like to see the buildroot relative file
  names.

  This class handles mapping from the coverage data stored at test time, which references source
  root stripped sources to the actual file names we want to see in the reports. In order for this
  to work, the environment in which we run generate the report must include all of the source files
  with their source roots still present.
  """

  def __init__(self, source_root, stripped_filename, test_time, coverage=None):
    # NB: This constructor is not compatible with the superclass. We intentionally do not call
    # super().
    self.source_root = source_root
    self.stripped_filename = stripped_filename
    self.test_time = test_time
    self.coverage = coverage
    self._parser = None
    self._source = None

  @property
  def full_filename(self):
    return os.path.join(self.source_root, self.stripped_filename)

  # We override this to handle our source root logic.
  @property
  def filename(self):
    return self.stripped_filename

  # We override this to handle our source root logic.
  def relative_filename(self):
    return self.full_filename

  @property
  def parser(self):
    if self._parser is None:
      self._parser = PythonParser(
        filename=self.stripped_filename if self.test_time else self.full_filename
      )
      self._parser.parse_source()
    return self._parser

  def no_branch_lines(self):
    return self.parser.lines_matching(
      join_regex(DEFAULT_PARTIAL[:]),
      join_regex(DEFAULT_PARTIAL_ALWAYS[:]),
    )

  def source(self):
    if self._source is None:
      self._source = get_python_source(self.full_filename)
    return self._source


class SourceRootRemappingPlugin(CoveragePlugin):
  """A plugin that knows how to map the source root stripped sources used in tests back to sources
  with source roots for reporting."""

  def __init__(self, chroot_build_root, stripped_files_to_source_roots, test_time):
    super().__init__()
    self.chroot_build_root = chroot_build_root
    self.stripped_files_to_source_roots = stripped_files_to_source_roots
    self.test_time = test_time

  def find_executable_files(self, top):
    # Coverage uses this to associate files with this plugin. We only want to be associated with
    # the sources we know about.
    if not top.startswith(self.chroot_build_root):
      return
    for dirname, _, filenames in os.walk(top):
      reldir = os.path.relpath(dirname, self.chroot_build_root)
      for filename in filenames:
        if os.path.join(reldir, filename) in self.stripped_files_to_source_roots:
          yield os.path.join(dirname, filename)

  def file_reporter(self, filename):
    stripped_file = os.path.relpath(filename, self.chroot_build_root)
    source_root = self.stripped_files_to_source_roots[stripped_file]
    return PantsPythonFileReporter(
      source_root=source_root, stripped_filename=stripped_file, test_time=self.test_time
    )


def coverage_init(reg, options):
  chroot_build_root = os.getcwd()
  stripped_files_to_source_roots = json.loads(options['stripped_files_to_source_roots'])
  test_time = json.loads(options['test_time'])
  reg.add_file_tracer(
    SourceRootRemappingPlugin(chroot_build_root, stripped_files_to_source_roots, test_time)
  )
