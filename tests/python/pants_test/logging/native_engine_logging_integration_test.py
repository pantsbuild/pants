# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_integration_test import PantsIntegrationTest, read_pantsd_log
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase


class NativeEngineLoggingTest(PantsIntegrationTest):
    def test_native_logging(self) -> None:
        expected_msg = r"\[DEBUG\] Launching \d+ root"
        pants_run = self.run_pants(["-linfo", "list", "3rdparty::"])
        self.assertNotRegex(pants_run.stderr, expected_msg)

        pants_run = self.run_pants(["-ldebug", "list", "3rdparty::"])
        self.assertRegex(pants_run.stderr, expected_msg)


class PantsdNativeLoggingTest(PantsDaemonIntegrationTestBase):
    def test_pantsd_file_logging(self) -> None:
        with self.pantsd_successful_run_context("debug") as ctx:
            daemon_run = ctx.runner(
                ["--backend-packages=pants.backend.python", "list", "3rdparty::"]
            )
            ctx.checker.assert_started()
            assert "[DEBUG] connecting to pantsd on port" in daemon_run.stderr_data

            pantsd_log = "\n".join(read_pantsd_log(ctx.workdir))
            assert "[DEBUG] logging initialized" in pantsd_log
