# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import signal
from typing import Mapping

import pytest
from workunit_logger.register import FINISHED_SUCCESSFULLY

from pants.testutil.pants_integration_test import (
    PantsResult,
    run_pants,
    setup_tmpdir,
    temporary_workdir,
)
from pants.util.dirutil import maybe_read_file
from pants_test.pantsd.pantsd_integration_test_base import attempts, launch_waiter


def workunit_logger_config(log_dest: str, *, pantsd: bool = True) -> Mapping:
    return {
        "GLOBAL": {
            "pantsd": pantsd,
            "backend_packages.add": ["workunit_logger", "pants.backend.python"],
        },
        "workunit-logger": {"dest": log_dest},
        "python": {"interpreter_constraints": "['>=3.7,<3.10']"},
    }


def run(
    args: list[str], success: bool = True, *, files: dict[str, str] | None = None
) -> tuple[PantsResult, str | None]:
    with setup_tmpdir(files or {}) as tmpdir:
        dest = os.path.join(tmpdir, "dest.log")
        normalized_args = [arg.format(tmpdir=tmpdir) for arg in args]
        pants_run = run_pants(normalized_args, config=workunit_logger_config(dest))
        if success:
            pants_run.assert_success()
            confirm_eventual_success(dest)
        else:
            pants_run.assert_failure()
        return pants_run, maybe_read_file(dest)


def confirm_eventual_success(log_dest: str) -> None:
    for _ in attempts("The log should eventually show that the SWH shut down."):
        content = maybe_read_file(log_dest)
        if content and FINISHED_SUCCESSFULLY in content:
            break


def test_list() -> None:
    run(["list", "{tmpdir}/foo::"], files={"foo/BUILD": "target()"})


def test_help() -> None:
    run(["help"])
    run(["--version"])


@pytest.mark.parametrize("pantsd", [True, False])
def test_ctrl_c(pantsd: bool) -> None:
    with temporary_workdir() as workdir:
        dest = os.path.join(workdir, "dest.log")

        # Start a pantsd run that will wait forever, then kill the pantsd client.
        client_handle, _, _, _ = launch_waiter(
            workdir=workdir, config=workunit_logger_config(dest, pantsd=pantsd)
        )
        client_pid = client_handle.process.pid
        os.kill(client_pid, signal.SIGINT)

        # Confirm that finish is still called (even though it may be backgrounded in the server).
        confirm_eventual_success(dest)


def test_restart() -> None:
    # Will trigger a restart
    run(["--pantsd-max-memory-usage=1", "roots"])
