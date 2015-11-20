# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.util.contextutil import environment_as, temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestPexRoot(PantsRunIntegrationTest):
  def test_root_set(self):
    with temporary_dir() as tmpdir:
      with environment_as(HOME=tmpdir):
        user_pex = os.path.join(tmpdir, '.pex')
        with self.temporary_workdir() as workdir:
          pants_run = self.run_pants_with_workdir(
                                    ['test',
                                      'tests/python/pants_test/backend/python/tasks:python_task'],
                                    workdir=workdir)
          self.assertTrue(pants_run)
          map(print, pants_run.stdout_data.split('\n'))
      self.assertFalse(os.path.exists(user_pex))
