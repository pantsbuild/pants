# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.py2_compat import assertRegex

class GoRunIntegrationTest(PantsRunIntegrationTest):

  def test_go_run_simple(self):
    args = ['run',
            'contrib/go/examples/src/go/hello',
            '--',
            '-n=3']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)

  def test_go_run_cgo(self):
    args = ['-q', 'run', 'contrib/go/examples/src/go/cgo']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)
    assertRegex(self, pants_run.stdout_data.strip(), r'^Random from C: \d+$')
