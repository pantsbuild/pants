# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


from contextlib import contextmanager
import os
import subprocess
from textwrap import dedent
import unittest

from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_open

from pants.base.build_environment import get_buildroot


class PantsRunIntegrationTest(unittest.TestCase):
  """A baseclass useful for integration tests for targets in the same repo"""

  PANTS_SUCCESS_CODE = 0
  PANTS_SCRIPT_NAME = 'pants'

  @contextmanager
  def run_pants(self, command, **kwargs):
    """Runs pants in a subprocess.

    :param list command: A list of command line arguments coming after `./pants`.
    :param kwargs: Extra keyword args to pass to `subprocess.Popen`.
    """
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
      pants_command = [os.path.join(get_buildroot(), self.PANTS_SCRIPT_NAME)] + command
      result = subprocess.call(pants_command, env=env, **kwargs)
      yield result
