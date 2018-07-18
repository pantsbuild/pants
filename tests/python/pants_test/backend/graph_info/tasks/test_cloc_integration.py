# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ClocIntegrationTest(PantsRunIntegrationTest):
  def test_cloc(self):
    pants_run = self.run_pants([
      'cloc',
      'testprojects/src/python/python_targets:test_library',
    ])
    self.assert_success(pants_run)
    # Strip out the header which is non-deterministic because it has speed information in it.
    stdout = str('\n'.join(pants_run.stdout_data.split('\n')[1:]))
    self.assertEquals(stdout, str("""-------------------------------------------------------------------------------
Language                     files          blank        comment           code
-------------------------------------------------------------------------------
Python                           1              3              3              4
-------------------------------------------------------------------------------

"""))
