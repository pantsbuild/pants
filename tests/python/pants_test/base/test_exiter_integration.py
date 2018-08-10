# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon


class ExiterIntegrationTest(PantsRunIntegrationTest):
  """Tests that "interesting" exceptions are properly rendered."""

  @ensure_daemon
  def test_unicode_containing_exception(self):
    """Test whether we can run a single target without special flags."""
    pants_run = self.run_pants(['test', 'testprojects/src/python/unicode/compilation_failure'])
    self.assert_failure(pants_run)

    self.assertIn('during bytecode compilation', pants_run.stderr_data)
    self.assertIn('import sys¡', pants_run.stderr_data)
