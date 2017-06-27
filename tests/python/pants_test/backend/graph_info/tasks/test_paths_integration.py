# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


# TODO: These tests duplicate the unit tests in `test_paths.py`, and should be removed in
# their favor once #4401 lands and allows unit tests to cover the v2 engine.
class PathsIntegrationTest(PantsRunIntegrationTest):
  def test_paths_single(self):
    pants_run = self.run_pants(['paths',
                                'testprojects/src/python/python_targets:test_library_direct_dependee',
                                'testprojects/src/python/python_targets:test_library'])
    self.assert_success(pants_run)
    self.assertIn('Found 1 path', pants_run.stdout_data)

  def test_paths_none(self):
    pants_run = self.run_pants(['paths',
                                'testprojects/src/python/python_targets:test_library',
                                'testprojects/src/python/python_targets:test_library_direct_dependee'])
    self.assert_success(pants_run)
    self.assertIn('Found 0 paths', pants_run.stdout_data)
