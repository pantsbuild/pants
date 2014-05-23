# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


import os
import subprocess
import unittest

from contextlib import contextmanager
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_open

from mock import patch


class PantsRunIntegrationTest(unittest.TestCase):
  """A baseclass useful for integration tests for targets in the same repo"""

  PANTS_SUCCESS_CODE = 0
  PANTS_GOAL_COMMAND = 'goal'
  PANTS_SCRIPT_NAME = 'pants'

  @contextmanager
  def run_pants(self, goal, targets, command_args=None):
    with temporary_dir() as work_dir:
      ini = dedent('''
              [DEFAULT]
              pants_workdir:  %(workdir)s
              ''' % dict(workdir=work_dir))

      ini_file_name = os.path.join(work_dir, 'pants.ini')
      with safe_open(ini_file_name, mode='w') as fp:
        fp.write(ini)
      env = os.environ.copy()
      env['PANTS_CONFIG_OVERRIDE'] = ini_file_name
      pants_commands = [os.path.join(get_buildroot(), self.PANTS_SCRIPT_NAME),
                        self.PANTS_GOAL_COMMAND, goal]  + targets + command_args
      result = subprocess.call(pants_commands, env=env)
      yield result
