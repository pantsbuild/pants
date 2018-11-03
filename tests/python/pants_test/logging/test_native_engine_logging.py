# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import PY3

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class NativeEngineLoggingTest(PantsRunIntegrationTest):
  def test_native_logging(self):

    pants_run = self.run_pants([
      "-linfo", "list", "3rdparty::"
    ])
    if PY3:
      self.assertNotRegex(pants_run.stderr_data, "DEBUG] Launching \\d+ root")
    else:
      self.assertNotRegexpMatches(pants_run.stderr_data, "DEBUG] Launching \\d+ root")

    pants_run = self.run_pants([
      "-ldebug", "list", "3rdparty::"
    ])
    self.assertRegexpMatches(pants_run.stderr_data, "DEBUG] Launching \\d+ root")
