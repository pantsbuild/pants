# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import os
import subprocess
import unittest

from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_open

from pants.base.build_environment import get_buildroot


class PantsRunIntegrationTest(unittest.TestCase):
  """A base class useful for integration tests for targets in the same repo."""

  PANTS_SUCCESS_CODE = 0
  PANTS_SCRIPT_NAME = 'pants'

  @contextmanager
  def run_pants(self, command, config=None, **kwargs):
    """Runs pants in a subprocess.

    :param list command: A list of command line arguments coming after `./pants`.
    :param config: Optional data for a generated ini file. A map of <section-name> ->
    map of key -> value. If order in the ini file matters, this should be an OrderedDict.
    :param kwargs: Extra keyword args to pass to `subprocess.Popen`.

    IMPORTANT NOTE: The subprocess will be run with --no-lock, so that it doesn't deadlock waiting
    for this process to release the workspace lock. It's the caller's responsibility to ensure
    that the invoked pants doesn't interact badly with this one.
    """
    config = config.copy() if config else {}
    with temporary_dir() as workdir:
      # We add workdir to the DEFAULT section, and also ensure that it's emitted first.
      default_section = config.pop('DEFAULT', {})
      default_section['pants_workdir'] = '%s' % workdir

      ini = ''
      for section, section_config in [('DEFAULT', default_section)] + config.items():
        ini += '\n[%s]\n' % section
        for key, val in section_config.items():
          ini += '%s: %s\n' % (key, val)

      ini_file_name = os.path.join(workdir, 'pants.ini')
      with safe_open(ini_file_name, mode='w') as fp:
        fp.write(ini)
      env = os.environ.copy()
      env['PANTS_CONFIG_OVERRIDE'] = ini_file_name
      pants_command = [os.path.join(get_buildroot(), self.PANTS_SCRIPT_NAME)] + command + ['--no-lock']
      result = subprocess.call(pants_command, env=env, **kwargs)
      yield result
