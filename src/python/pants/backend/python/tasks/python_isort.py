# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

import isort
from pants.backend.python.tasks.python_task import PythonTask
from pants.option.custom_types import file_option


class IsortPythonTask(PythonTask):
  """Task to provide autoformat with python isort module."""

  _PYTHON_SOURCE_EXTENSION = '.py'

  def __init__(self, *args, **kwargs):
    super(IsortPythonTask, self).__init__(*args, **kwargs)
    self.options = self.get_options()

  @classmethod
  def register_options(cls, register):
    super(IsortPythonTask, cls).register_options(register)
    register('--skip', type=bool, default=False,
             help='If enabled, skip isort task.')
    register('--config-file', fingerprint=True, type=file_option, default='./.isort.cfg',
             help='Specify path to isort config file.')

  def execute(self):
    """Run isort on all found source python files."""
    if self.options.skip:
      return

    for source in self._calculate_sources(self.context.targets()):
      isort.SortImports(file_path=source, settings_path=self.options.config_file)

  def _calculate_sources(self, targets):
    """Generate a set of source files from the given targets."""
    sources = set()
    for target in targets:
      sources.update(
        source for source in target.sources_relative_to_buildroot()
        if os.path.splitext(source)[1] == self._PYTHON_SOURCE_EXTENSION
      )
    return sources
