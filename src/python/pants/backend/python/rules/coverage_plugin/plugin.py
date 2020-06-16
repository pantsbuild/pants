# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os

from coverage import CoveragePlugin, FileTracer
from coverage.config import DEFAULT_PARTIAL, DEFAULT_PARTIAL_ALWAYS
from coverage.misc import join_regex
from coverage.parser import PythonParser
from coverage.python import PythonFileReporter


class PantsFileTracer(FileTracer):
  """This tells Coverage which files Pants 'owns'."""

  def __init__(self, filename):
    super(PantsFileTracer, self).__init__()
    self.filename = filename

  def source_filename(self):
    return self.filename


class PantsPythonFileReporter(PythonFileReporter):
  def __init__(self, stripped_filename, full_filename):
    # NB: This constructor is not compatible with the superclass. We intentionally do not call
    # super().
    self.stripped_filename = stripped_filename
    self.full_filename = full_filename
    self.coverage = None
    self._parser = None
    self._source = None

  # We override this to handle our source root logic.
  @property
  def filename(self):
    return self.stripped_filename

  # This is what gets used in reports.
  def relative_filename(self):
    return self.full_filename

  @property
  def parser(self):
    if self._parser is None:
      self._parser = PythonParser(filename=self.full_filename)
      self._parser.parse_source()
    return self._parser

  def no_branch_lines(self):
    return self.parser.lines_matching(
      join_regex(DEFAULT_PARTIAL[:]),
      join_regex(DEFAULT_PARTIAL_ALWAYS[:]),
    )


class SourceRootRemappingPlugin(CoveragePlugin):
  """A plugin that knows how to restore source roots from stripped files in Coverage reports."""

  def __init__(self, chroot_path, stripped_files_to_source_roots):
    super(SourceRootRemappingPlugin, self).__init__()
    self.chroot_path = chroot_path
    self.stripped_files_to_source_roots = stripped_files_to_source_roots

  def file_tracer(self, filename):
    if not filename.startswith(self.chroot_path):
      return None
    stripped_file = os.path.relpath(filename, self.chroot_path)
    if stripped_file in self.stripped_files_to_source_roots:
      return PantsFileTracer(filename)

  def file_reporter(self, filename):
    stripped_file = os.path.relpath(filename, self.chroot_path)
    source_root = self.stripped_files_to_source_roots[stripped_file]
    return PantsPythonFileReporter(
      stripped_filename=stripped_file,
      full_filename=os.path.join(source_root, stripped_file),
    )


def coverage_init(reg, options):
  chroot_path = os.getcwd()
  stripped_files_to_source_roots = json.loads(options['stripped_files_to_source_roots'])
  reg.add_file_tracer(SourceRootRemappingPlugin(chroot_path, stripped_files_to_source_roots))
