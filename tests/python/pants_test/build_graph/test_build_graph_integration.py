# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BuildGraphIntegrationTest(PantsRunIntegrationTest):

  @contextmanager
  def _renamed(self, prefix, test_name, real_name):
    real_path = os.path.join(prefix, real_name)
    test_path = os.path.join(prefix, test_name)
    print('renaming from {} to {}'.format(real_path, test_path))
    try:
      os.rename(test_path, real_path)
      yield
    finally:
      os.rename(real_path, test_path)

  def test_cycle(self):
    prefix = 'testprojects/src/java/org/pantsbuild/testproject'
    with self._renamed(os.path.join(prefix, 'cycle1'), 'TEST_BUILD', 'BUILD'):
      with self._renamed(os.path.join(prefix, 'cycle2'), 'TEST_BUILD', 'BUILD'):
        pants_run = self.run_pants(['compile', os.path.join(prefix, 'cycle1')])
        self.assert_failure(pants_run)
        self.assertIn('Cycle detected', pants_run.stderr_data)
