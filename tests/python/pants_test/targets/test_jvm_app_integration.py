# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestJvmAppIntegrationTest(PantsRunIntegrationTest):
  def test_smoke(self):
    pants_run = self.run_pants(['bundle',
                                'testprojects/src/java/org/pantsbuild/testproject/bundle'])
    self.assert_success(pants_run)

  def test_missing_files(self):
    pants_run = self.run_pants(['bundle',
                                'testprojects/src/java/org/pantsbuild/testproject/bundle:missing-files'])
    self.assert_failure(pants_run)
