# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import signal
from typing import List, Mapping, Tuple

from workunit_logger.register import FINISHED_SUCCESSFULLY

from pants.testutil.pants_integration_test import (
    PantsResult,
    run_pants,
    setup_tmpdir,
    temporary_workdir,
)
from pants.util.dirutil import maybe_read_file
from pants_test.pantsd.pantsd_integration_test_base import attempts, launch_waiter


def workunit_logger_config(log_dest: str) -> Mapping:
    return {
        "GLOBAL": {
            "backend_packages.add": ["workunit_logger", "pants.backend.python"],
        },
        "workunit-logger": {"dest": log_dest},
    }


def run(args: List[str], success: bool = True) -> Tuple[PantsResult, str | None]:
    with setup_tmpdir({}) as tmpdir:
        dest = os.path.join(tmpdir, "dest.log")
        pants_run = run_pants(args, config=workunit_logger_config(dest))
        log_content = maybe_read_file(dest)
        if success:
            pants_run.assert_success()
            assert log_content
            assert FINISHED_SUCCESSFULLY in log_content
        else:
            pants_run.assert_failure()
        return pants_run, log_content


def test_list() -> None:
    run(["list", "3rdparty::"])


def test_help() -> None:
    run(["help"])
    run(["--version"])


def test_ctrl_c() -> None:
    with temporary_workdir() as workdir:
        dest = os.path.join(workdir, "dest.log")

        # Start a pantsd run that will wait forever, then kill the pantsd client.
        client_handle, _, _ = launch_waiter(workdir=workdir, config=workunit_logger_config(dest))
        client_pid = client_handle.process.pid
        os.kill(client_pid, signal.SIGINT)

        # Confirm that finish is still called (even though it may be backgrounded in the server).
        for _ in attempts("The log should eventually show that the SWH shut down."):
            content = maybe_read_file(dest)
            if content and FINISHED_SUCCESSFULLY in content:
                break
