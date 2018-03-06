# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.backend.python.subsystems.isort import Isort
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.task import Task
from pants.util.process_handler import subprocess


# TODO: Should be named IsortRun, for consistency.
class IsortPythonTask(FmtTaskMixin, Task):
  """Autoformats Python source files with isort.

  isort binary is built at contrib/python/src/python/pants/contrib/python/isort,
  then uploaded to
  https://github.com/pantsbuild/binaries/tree/gh-pages/build-support/scripts

  TODO: Explain why we don't invoke isort directly.

  Behavior:
  ./pants fmt.isort <targets> -- <args, e.g. "--recursive ."> will sort the files only related
    to specified targets, but the way of finding the config(s) is vanilla. If no target is
    specified or no python source file is found in <targets>, it would be a no-op.
  """

  NOOP_MSG_HAS_TARGET_BUT_NO_SOURCE = "No-op: no Python source file found in target(s)."

  _PYTHON_SOURCE_EXTENSION = '.py'

  @classmethod
  def subsystem_dependencies(cls):
    return super(IsortPythonTask, cls).subsystem_dependencies() + (Isort, )

  def __init__(self, *args, **kwargs):
    super(IsortPythonTask, self).__init__(*args, **kwargs)
    self.options = self.get_options()

  @classmethod
  def register_options(cls, register):
    super(IsortPythonTask, cls).register_options(register)
    register('--version', advanced=True, fingerprint=True, default='4.2.5',
             removal_version='1.7.0.dev0', removal_hint='Use --version in scope isort',
             help='Version of isort.')

  def execute(self, test_output_file=None):
    sources = self._calculate_isortable_python_sources(
      self.get_targets(self.is_non_synthetic_python_target))

    if not sources:
      logging.debug(self.NOOP_MSG_HAS_TARGET_BUT_NO_SOURCE)
      return

    isort_script = Isort.global_instance().select(context=self.context)
    cmd = [isort_script] + self.get_passthru_args() + sources
    logging.debug(' '.join(cmd))

    try:
      subprocess.check_call(cmd, cwd=get_buildroot(),
                            stderr=test_output_file, stdout=test_output_file)
    except subprocess.CalledProcessError as e:
      raise TaskError('{} ... exited non-zero ({}).'.format(' '.join(cmd), e.returncode))

  def _calculate_isortable_python_sources(self, targets):
    """Generate a set of source files from the given targets."""
    sources = set()
    for target in targets:
      sources.update(
        source for source in target.sources_relative_to_buildroot()
        if os.path.splitext(source)[1] == self._PYTHON_SOURCE_EXTENSION
      )
    return list(sources)

  @staticmethod
  def is_non_synthetic_python_target(target):
    return (not target.is_synthetic
            and isinstance(target, (PythonLibrary, PythonBinary, PythonTests)))

  @classmethod
  def supports_passthru_args(cls):
    return True
