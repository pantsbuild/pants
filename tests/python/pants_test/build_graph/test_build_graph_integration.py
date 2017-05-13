# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BuildGraphIntegrationTest(PantsRunIntegrationTest):

  def test_cycle(self):
    prefix = 'testprojects/src/java/org/pantsbuild/testproject'
    with self.file_renamed(os.path.join(prefix, 'cycle1'), 'TEST_BUILD', 'BUILD'):
      with self.file_renamed(os.path.join(prefix, 'cycle2'), 'TEST_BUILD', 'BUILD'):
        pants_run = self.run_pants(['compile', os.path.join(prefix, 'cycle1')])
        self.assert_failure(pants_run)
        self.assertIn('Cycle detected', pants_run.stderr_data)
