# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.py2_compat import assertNotRegex, assertRegex


class NativeEngineLoggingTest(PantsRunIntegrationTest):

  @classmethod
  def use_pantsd_env_var(cls):
    """
    Some of the tests here expect to read the standard error after an intentional failure.
    However, when pantsd is enabled, these errors are logged to logs/exceptions.<pid>.log
    So stderr appears empty. (see #7320)
    """
    return False

  def test_native_logging(self):

    pants_run = self.run_pants([
      "-linfo", "list", "3rdparty::"
    ])
    assertNotRegex(self, pants_run.stderr_data, "DEBUG] Launching \\d+ root")

    pants_run = self.run_pants([
      "-ldebug", "list", "3rdparty::"
    ])
    assertRegex(self, pants_run.stderr_data, "DEBUG] Launching \\d+ root")
