# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

from pants.testutil.pants_integration_test import read_pants_log, run_pants, setup_tmpdir
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase


def test_native_logging() -> None:
    expected_msg = r"\[DEBUG\] Launching \d+ root"

    with setup_tmpdir({"foo/BUILD": "files(sources=[])"}) as tmpdir:
        pants_run = run_pants(
            ["-linfo", "--backend-packages=pants.backend.python", "list", f"{tmpdir}/foo::"]
        )
        pants_run.assert_success()
        assert not bool(re.search(expected_msg, pants_run.stderr))

        pants_run = run_pants(
            ["-ldebug", "--backend-packages=pants.backend.python", "list", f"{tmpdir}/foo::"]
        )
        pants_run.assert_success()
        assert bool(re.search(expected_msg, pants_run.stderr))


class PantsdNativeLoggingTest(PantsDaemonIntegrationTestBase):
    def test_pantsd_file_logging(self) -> None:
        with self.pantsd_successful_run_context("debug") as ctx:
            with setup_tmpdir({"foo/BUILD": "files(sources=[])"}) as tmpdir:
                daemon_run = ctx.runner(
                    ["--backend-packages=pants.backend.python", "list", f"{tmpdir}/foo::"]
                )
                ctx.checker.assert_started()
                assert "[DEBUG] Connecting to pantsd on port" in daemon_run.stderr
                assert "[DEBUG] Connected to pantsd" in daemon_run.stderr

                pants_log = "\n".join(read_pants_log(ctx.workdir))
                assert "[INFO] handling request" in pants_log
