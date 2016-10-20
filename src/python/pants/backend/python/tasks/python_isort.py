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
  """Autoformats Python source files with isort.

  isort binary is built at contrib/python/src/python/pants/contrib/python/isort:isort, then uploaded to
  https://github.com/pantsbuild/binaries/tree/gh-pages/build-support/scripts

  Behavior:
  1. ./pants fmt.isort <targets> -- <args, e.g. "--recursive ."> will sort the files only related
      to specified targets, but the way of finding the config(s) is vanilla. If no python source file
      is found, it would be no-op.
  2. ./pants fmt.isort -- <args, e.g. "--recursive ."> is equivalent to isort <args>, meaning both
      the files to be sorted and the way of finding the config(s) are vanilla.
  """

  NOOP_MSG_HAS_TARGET_BUT_NO_SOURCE = "No-op: no Python source file found in target(s)."

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

    if self.options.skip:
      return

    isort_script = BinaryUtil.Factory.create().select_script('scripts/isort', self.options.version, 'isort.pex')

    targets = self.context.targets()

    sources = self._calculate_isortable_python_sources(targets)

    # If target(s) are specified but no python source(s) are found, no op.
    if targets and not sources:
      logging.info(self.NOOP_MSG_HAS_TARGET_BUT_NO_SOURCE)
      return

    cmd = [isort_script] + self.get_passthru_args() + sources
    logging.debug(' '.join(cmd))

    try:
      subprocess.check_call(cmd, cwd=get_buildroot(), stderr=test_output_file, stdout=test_output_file)
    except subprocess.CalledProcessError as e:
      raise TaskError('{} ... exited non-zero ({}).'.format(' '.join(cmd), e.returncode))

  def _calculate_isortable_python_sources(self, targets):
    """Generate a set of source files from the given targets."""
    python_eval_targets = filter(self.is_non_synthetic_python_target, targets)
    sources = set()
    for target in python_eval_targets:
      sources.update(
        source for source in target.sources_relative_to_buildroot()
        if os.path.splitext(source)[1] == self._PYTHON_SOURCE_EXTENSION
      )
    return list(sources)

  @staticmethod
  def is_non_synthetic_python_target(target):
    return not target.is_synthetic and isinstance(target, (PythonLibrary, PythonBinary, PythonTests))

  @classmethod
  def supports_passthru_args(cls):
    return True
