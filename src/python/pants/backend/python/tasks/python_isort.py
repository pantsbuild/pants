# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import subprocess

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.binaries.binary_util import BinaryUtil


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
             help='If true, skip isort task.')
    register('--version', advanced=True, fingerprint=True, default='4.2.5', help='Version of isort.')

  def execute(self, test_output_file=None):
    """Run isort on source python files.

    isort binary is built at contrib/python/src/python/pants/contrib/python/isort:isort
    """
    if self.options.skip:
      return

    isort_script = BinaryUtil.Factory.create().select_script('scripts/isort', self.options.version, 'isort.pex')

    # If neither targets nor passthru are specified, isort ::
    if not self.context.target_roots and not self.get_passthru_args():
      args = list(self._calculate_sources())
    else:
      sources = list(self._calculate_sources(self.context.targets()))
      args = self.get_passthru_args() + sources

    if len(args) == 0:
      logging.debug("Noop isort")
      return

    cmd = [isort_script] + args
    logging.debug(' '.join(cmd))

    try:
      subprocess.check_call(cmd, cwd=get_buildroot(), stderr=test_output_file, stdout=test_output_file)
    except subprocess.CalledProcessError as e:
      raise TaskError('{} ... exited non-zero ({}).'.format(' '.join(cmd), e.returncode))

  def _calculate_sources(self, targets=None):
    """Generate a set of source files from the given targets."""
    if targets is None:
      targets = self.context.scan().targets(predicate=lambda tgt: not tgt.is_synthetic)

    python_eval_targets = filter(self.is_isortable, targets)
    sources = set()
    for target in python_eval_targets:
      sources.update(
        source for source in target.sources_relative_to_buildroot()
        if os.path.splitext(source)[1] == self._PYTHON_SOURCE_EXTENSION
      )
    return sources

  @classmethod
  def supports_passthru_args(cls):
    return True

  @staticmethod
  def is_isortable(target):
    return isinstance(target, (PythonLibrary, PythonBinary, PythonTests))
