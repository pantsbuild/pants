# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.pants_run_integration_test import PantsRunIntegrationTest, read_pantsd_log
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase


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
    expected_msg = "\[DEBUG\] engine::scheduler: Launching \d+ root"
    pants_run = self.run_pants([
      "-linfo", "list", "src/scala::"
    ])
    self.assertNotRegex(pants_run.stderr_data, expected_msg)

    pants_run = self.run_pants([
      "-ldebug", "list", "src/scala::"
    ])
    self.assertRegex(pants_run.stderr_data, expected_msg)


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
