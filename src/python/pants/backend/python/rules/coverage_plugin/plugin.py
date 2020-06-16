# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os

from coverage import CoveragePlugin
from coverage.config import DEFAULT_PARTIAL, DEFAULT_PARTIAL_ALWAYS
from coverage.misc import join_regex
from coverage.parser import PythonParser
from coverage.python import PythonFileReporter, get_python_source


# Note: This plugin will appear to do nothing when tests are running. This is expected. The only
# thing Coverage does with this plugin at test time is storing the class name in its SQL data,
# i.e.: `__pants_coverage_plugin__.SourceRootRemappingPlugin`. This ensures that the plugin is used
# in later Coverage commands like `coverage html`.

class PantsPythonFileReporter(PythonFileReporter):
  def __init__(self, source_root, stripped_filename, coverage=None):
    # NB: This constructor is not compatible with the superclass. We intentionally do not call
    # super().
    self.source_root = source_root
    self.stripped_filename = stripped_filename
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
      self._parser = PythonParser(filename=self.full_filename)
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
  """A plugin that knows how to restore source roots from stripped files in Coverage reports."""

  def __init__(self, chroot_path, stripped_files_to_source_roots):
    super(SourceRootRemappingPlugin, self).__init__()
    self.chroot_path = chroot_path
    self.stripped_files_to_source_roots = stripped_files_to_source_roots

  def find_executable_files(self, top):
    # Coverage uses this to associate files with this plugin. We only want to be associated with
    # the sources we know about.
    if not top.startswith(self.chroot_path):
      return
    for dirname, _, filenames in os.walk(top):
      reldir = os.path.relpath(dirname, self.chroot_path)
      for filename in filenames:
        if os.path.join(reldir, filename) in self.stripped_files_to_source_roots:
          yield os.path.join(dirname, filename)

  def file_reporter(self, filename):
    stripped_file = os.path.relpath(filename, self.chroot_path)
    source_root = self.stripped_files_to_source_roots[stripped_file]
    return PantsPythonFileReporter(source_root=source_root, stripped_filename=stripped_file)


def coverage_init(reg, options):
  chroot_path = os.getcwd()
  stripped_files_to_source_roots = json.loads(options['stripped_files_to_source_roots'])
  reg.add_file_tracer(SourceRootRemappingPlugin(chroot_path, stripped_files_to_source_roots))
