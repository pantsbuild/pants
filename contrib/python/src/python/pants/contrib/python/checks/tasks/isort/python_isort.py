# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

import isort
from pants.backend.python.tasks.python_task import PythonTask

from pants.option.custom_types import file_option


class IsortPythonTask(PythonTask):
  """Add additonal steps to OSS PythonCheckStyleTask."""

  _PYTHON_SOURCE_EXTENSION = '.py'

  def __init__(self, *args, **kwargs):
    super(IsortPythonTask, self).__init__(*args, **kwargs)
    self.options = self.get_options()

  @classmethod
  def register_options(cls, register):
    super(IsortPythonTask, cls).register_options(register)
    register('--config-file', fingerprint=True, type=file_option, default=None,
             help='Specify isort config file.')

  def execute(self):
    """Run isort on all found source files."""

    if self.options.config_file is None:
      logging.error("Please specify config file with --config-file")
      exit(1)

    for source in self.calculate_sources(self.context.targets()):
      isort.SortImports(file_path=source, settings_path=self.options.config_file)

  def calculate_sources(self, targets):
    """Generate a set of source files from the given targets."""
    sources = set()
    for target in targets:
      sources.update(
        source for source in target.sources_relative_to_buildroot()
        if source.endswith(self._PYTHON_SOURCE_EXTENSION)
      )
    return sources