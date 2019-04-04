# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest, read_pantsd_log
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase
from pants_test.testutils.py2_compat import assertNotRegex, assertRegex


class NativeEngineLoggingTest(PantsRunIntegrationTest):
  def test_native_logging(self):
    expected_msg = "\[DEBUG\] engine::scheduler: Launching \d+ root"
    pants_run = self.run_pants([
      "-linfo", "list", "src/scala::"
    ])
    assertNotRegex(self, pants_run.stderr_data, expected_msg)

    pants_run = self.run_pants([
      "-ldebug", "list", "src/scala::"
    ])
    assertRegex(self, pants_run.stderr_data, expected_msg)


class PantsdNativeLoggingTest(PantsDaemonIntegrationTestBase):
  def test_pantsd_file_logging(self):
    with self.pantsd_successful_run_context('debug') as (pantsd_run, checker, workdir, _):
      daemon_run = pantsd_run(["list", "3rdparty::"])
      checker.assert_started()

      self.assert_run_contains_log(
        "connecting to pantsd on port",
        "DEBUG",
        "pants.bin.remote_pants_runner",
        daemon_run,
      )

      pantsd_log = '\n'.join(read_pantsd_log(workdir))
      self.assert_contains_log(
        "logging initialized",
        "DEBUG",
        "pants.pantsd.pants_daemon",
        pantsd_log,
      )
