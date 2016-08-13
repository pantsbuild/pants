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
  1. `./pants fmt.isort <targets>` will sort the files only related to specified targets, but the way of finding the config(s) is vanilla.
  2. Additional arguments can be passed as passthru. e.g. `./pants fmt.isort <targets> -- --check-only`
  3. `./pants fmt.isort -- <args, e.g. "--recursive .">` means both the files to be sorted and the way of finding the config(s) are vanilla.
  4. `./pants fmt.isort` means `./pants fmt.isort ::` and NOT the entire repo directory which could include files not in any target.
  """

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

    # If neither targets nor passthru are specified, isort ::
    if not self.context.target_roots and not self.get_passthru_args():
      targets = self.context.scan().targets()
    else:
      targets = self.context.targets()

    sources = self._calculate_isortable_python_sources(targets)
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
