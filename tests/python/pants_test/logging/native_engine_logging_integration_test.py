# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

from pants.testutil.pants_integration_test import read_pantsd_log, run_pants
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase


def test_native_logging() -> None:
    expected_msg = r"\[DEBUG\] Launching \d+ root"
    pants_run = run_pants(
        ["-linfo", "--backend-packages=pants.backend.python", "list", "3rdparty::"]
    )
    pants_run.assert_success()
    assert not bool(re.search(expected_msg, pants_run.stderr))

    pants_run = run_pants(
        ["-ldebug", "--backend-packages=pants.backend.python", "list", "3rdparty::"]
    )
    pants_run.assert_success()
    assert bool(re.search(expected_msg, pants_run.stderr))


class PantsdNativeLoggingTest(PantsDaemonIntegrationTestBase):
    def test_pantsd_file_logging(self) -> None:
        with self.pantsd_successful_run_context("debug") as ctx:
            daemon_run = ctx.runner(
                ["--backend-packages=pants.backend.python", "list", "3rdparty::"]
            )
            ctx.checker.assert_started()
            assert "[DEBUG] connecting to pantsd on port" in daemon_run.stderr_data

            pantsd_log = "\n".join(read_pantsd_log(ctx.workdir))
            assert "[DEBUG] Logging reinitialized in pantsd context" in pantsd_log
