# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import signal
import time
from textwrap import dedent
from typing import List, Tuple

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.testutil.pants_integration_test import run_pants_with_workdir
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import read_file
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase


def lifecycle_stub_cmdline() -> List[str]:
    # Load the testprojects pants-plugins to get some testing tasks and subsystems.
    testproject_backend_src_dir = os.path.join(
        get_buildroot(), "testprojects/pants-plugins/src/python"
    )
    testproject_backend_pkg_name = "test_pants_plugin"
    lifecycle_stub_cmdline = [
        "--no-pantsd",
        f"--pythonpath=+['{testproject_backend_src_dir}']",
        f"--backend-packages=+['{testproject_backend_pkg_name}']",
        # This task will always raise an exception.
        "lifecycle-stub-goal",
    ]

    return lifecycle_stub_cmdline


def get_log_file_paths(workdir: str, pid: int) -> Tuple[str, str]:
    pid_specific_log_file = ExceptionSink.exceptions_log_path(for_pid=pid, in_dir=workdir)
    assert os.path.isfile(pid_specific_log_file)

    shared_log_file = ExceptionSink.exceptions_log_path(in_dir=workdir)
    assert os.path.isfile(shared_log_file)

    assert pid_specific_log_file != shared_log_file

    return (pid_specific_log_file, shared_log_file)


def assert_unhandled_exception_log_matches(pid: int, file_contents: str, namespace: str) -> None:
    regex_str = f"""\
timestamp: ([^\n]+)
process title: ([^\n]+)
sys\\.argv: ([^\n]+)
pid: {pid}
Exception caught: \\([^)]*\\)
(.|\n)*

Exception message:.* 1 Exception encountered:

  ResolveError: 'this-target-does-not-exist' was not found in namespace '{namespace}'\\. Did you mean one of:
"""
    assert re.match(regex_str, file_contents)


def assert_graceful_signal_log_matches(pid: int, signum, signame, contents: str) -> None:
    regex_str = """\
timestamp: ([^\n]+)
process title: ([^\n]+)
sys\\.argv: ([^\n]+)
pid: {pid}
Signal {signum} \\({signame}\\) was raised\\. Exiting with failure\\.
""".format(
        pid=pid, signum=signum, signame=signame
    )
    assert re.search(regex_str, contents)


def test_logs_unhandled_exception() -> None:
    directory = "testprojects/src/python/hello/main"
    with temporary_dir() as tmpdir:
        pants_run = run_pants_with_workdir(
            ["--no-pantsd", "list", f"{directory}:this-target-does-not-exist"],
            workdir=tmpdir,
            # The backtrace should be omitted when --print-stacktrace=False.
            print_stacktrace=False,
            hermetic=False,
        )

        pants_run.assert_failure()

        regex = f"'this-target-does-not-exist' was not found in namespace '{directory}'\\. Did you mean one of:"
        assert re.search(regex, pants_run.stderr)

        pid_specific_log_file, shared_log_file = get_log_file_paths(tmpdir, pants_run.pid)
        assert_unhandled_exception_log_matches(
            pants_run.pid, read_file(pid_specific_log_file), namespace=directory
        )
        assert_unhandled_exception_log_matches(
            pants_run.pid, read_file(shared_log_file), namespace=directory
        )


def test_fails_ctrl_c_on_import() -> None:
    with temporary_dir() as tmpdir:
        # TODO: figure out the cwd of the pants subprocess, not just the "workdir"!
        pants_run = run_pants_with_workdir(
            lifecycle_stub_cmdline(),
            workdir=tmpdir,
            extra_env={"_RAISE_KEYBOARDINTERRUPT_ON_IMPORT": "True"},
        )
        pants_run.assert_failure()

        assert (
            dedent(
                """\
                Interrupted by user:
                ctrl-c during import!
                """
            )
            in pants_run.stderr
        )

        pid_specific_log_file, shared_log_file = get_log_file_paths(tmpdir, pants_run.pid)

        assert "" == read_file(pid_specific_log_file)
        assert "" == read_file(shared_log_file)


def test_fails_ctrl_c_ffi_extern() -> None:
    with temporary_dir() as tmpdir:
        pants_run = run_pants_with_workdir(
            command=lifecycle_stub_cmdline(),
            workdir=tmpdir,
            extra_env={"_RAISE_KEYBOARDINTERRUPT_IN_EXTERNS": "run_lifecycle_stubs"},
        )
        pants_run.assert_failure()

        assert (
            "KeyboardInterrupt: ctrl-c interrupted execution of a ffi method!" in pants_run.stderr
        )

        pid_specific_log_file, shared_log_file = get_log_file_paths(tmpdir, pants_run.pid)

        assert "KeyboardInterrupt: ctrl-c interrupted execution of a ffi method!" in read_file(
            pid_specific_log_file
        )
        assert "KeyboardInterrupt: ctrl-c interrupted execution of a ffi method!" in read_file(
            shared_log_file
        )


class ExceptionSinkIntegrationTest(PantsDaemonIntegrationTestBase):
    hermetic = False

    def test_dumps_logs_on_signal(self):
        """Send signals which are handled, but don't get converted into a KeyboardInterrupt."""
        signal_names = {
            signal.SIGQUIT: "SIGQUIT",
            signal.SIGTERM: "SIGTERM",
        }
        for (signum, signame) in signal_names.items():
            with self.pantsd_successful_run_context() as ctx:
                ctx.runner(["help"])
                pid = ctx.checker.assert_started()
                os.kill(pid, signum)

                time.sleep(5)

                # Check that the logs show a graceful exit by signal.
                pid_specific_log_file, shared_log_file = get_log_file_paths(ctx.workdir, pid)
                assert_graceful_signal_log_matches(
                    pid, signum, signame, read_file(pid_specific_log_file)
                )
                assert_graceful_signal_log_matches(pid, signum, signame, read_file(shared_log_file))

    def test_dumps_traceback_on_sigabrt(self):
        # SIGABRT sends a traceback to the log file for the current process thanks to
        # faulthandler.enable().
        with self.pantsd_successful_run_context() as ctx:
            ctx.runner(["help"])
            pid = ctx.checker.assert_started()
            os.kill(pid, signal.SIGABRT)

            time.sleep(5)

            # Check that the logs show an abort signal and the beginning of a traceback.
            pid_specific_log_file, shared_log_file = get_log_file_paths(ctx.workdir, pid)
            regex_str = """\
Fatal Python error: Aborted

Thread [^\n]+ \\(most recent call first\\):
"""

            assert re.search(regex_str, read_file(pid_specific_log_file))

            # faulthandler.enable() only allows use of a single logging file at once for fatal tracebacks.
            self.assertEqual("", read_file(shared_log_file))
