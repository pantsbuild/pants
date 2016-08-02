# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import isort

from pants.contrib.python.checks.tasks.checkstyle.checker import PythonCheckStyleTask


class IsortPythonTask(PythonCheckStyleTask):
  """Add additonal steps to OSS PythonCheckStyleTask."""

  @classmethod
  def register_options(cls, register):
    super(IsortPythonTask, cls).register_options(register)
    # register('--enable-import-sorting', fingerprint=True, default=False, type=bool,
    #          help='sort python imports automatically.')
    # register('--prompt', default=False, type=bool,
    #          help='If enabled, skip this style checker.')

  def execute(self):
    """Run Checkstyle on all found source files."""
    # if self.options.skip:
    #   return
    for source in self.calculate_sources(self.context.targets()):
      isort.SortImports(file_path=source, settings_path='./.isort.cfg')
