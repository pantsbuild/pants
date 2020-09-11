# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import signal
import time
from textwrap import dedent

import pytest

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import read_file
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase


class ExceptionSinkIntegrationTest(PantsDaemonIntegrationTestBase):
    def _assert_unhandled_exception_log_matches(self, pid, file_contents):
        self.assertRegex(
            file_contents,
            """\
timestamp: ([^\n]+)
process title: ([^\n]+)
sys\\.argv: ([^\n]+)
pid: {pid}
Exception caught: \\([^)]*\\)
(.|\n)*

Exception message:.* 1 Exception encountered:

  ResolveError: "this-target-does-not-exist" was not found in namespace ""\\. Did you mean one of:
""".format(
                pid=pid
            ),
        )
        # Ensure we write all output such as stderr and reporting files before closing any streams.
        self.assertNotIn("Exception message: I/O operation on closed file.", file_contents)

    def _get_log_file_paths(self, workdir, pid):
        pid_specific_log_file = ExceptionSink.exceptions_log_path(for_pid=pid, in_dir=workdir)
        self.assertTrue(os.path.isfile(pid_specific_log_file))

        shared_log_file = ExceptionSink.exceptions_log_path(in_dir=workdir)
        self.assertTrue(os.path.isfile(shared_log_file))

        self.assertNotEqual(pid_specific_log_file, shared_log_file)

        return (pid_specific_log_file, shared_log_file)

    def test_fails_ctrl_c_ffi_extern(self):
        with temporary_dir() as tmpdir:
            with environment_as(_RAISE_KEYBOARDINTERRUPT_IN_EXTERNS="True"):
                pants_run = self.run_pants_with_workdir(
                    self._lifecycle_stub_cmdline(), workdir=tmpdir
                )
                self.assert_failure(pants_run)

                self.assertIn(
                    "KeyboardInterrupt: ctrl-c interrupted execution of a ffi method!",
                    pants_run.stderr_data,
                )

                pid_specific_log_file, shared_log_file = self._get_log_file_paths(
                    tmpdir, pants_run.pid
                )

                self.assertIn(
                    "KeyboardInterrupt: ctrl-c interrupted execution of a ffi method!",
                    read_file(pid_specific_log_file),
                )
                self.assertIn(
                    "KeyboardInterrupt: ctrl-c interrupted execution of a ffi method!",
                    read_file(shared_log_file),
                )

    def test_fails_ctrl_c_on_import(self):
        with temporary_dir() as tmpdir:
            with environment_as(_RAISE_KEYBOARDINTERRUPT_ON_IMPORT="True"):
                # TODO: figure out the cwd of the pants subprocess, not just the "workdir"!
                pants_run = self.run_pants_with_workdir(
                    self._lifecycle_stub_cmdline(), workdir=tmpdir
                )
                self.assert_failure(pants_run)

                self.assertIn(
                    dedent(
                        """\
                        Interrupted by user:
                        ctrl-c during import!
                        """
                    ),
                    pants_run.stderr_data,
                )

                pid_specific_log_file, shared_log_file = self._get_log_file_paths(
                    tmpdir, pants_run.pid
                )

                self.assertEqual("", read_file(pid_specific_log_file))
                self.assertEqual("", read_file(shared_log_file))

    def test_logs_unhandled_exception(self):
        with temporary_dir() as tmpdir:
            pants_run = self.run_pants_with_workdir(
                ["--no-pantsd", "list", "//:this-target-does-not-exist"],
                workdir=tmpdir,
                # The backtrace should be omitted when --print-exception-stacktrace=False.
                print_exception_stacktrace=False,
            )
            self.assert_failure(pants_run)
            self.assertRegex(
                pants_run.stderr_data,
                """\
"this-target-does-not-exist" was not found in namespace ""\\. Did you mean one of:
""",
            )
            pid_specific_log_file, shared_log_file = self._get_log_file_paths(tmpdir, pants_run.pid)
            self._assert_unhandled_exception_log_matches(
                pants_run.pid, read_file(pid_specific_log_file)
            )
            self._assert_unhandled_exception_log_matches(pants_run.pid, read_file(shared_log_file))

    def _assert_graceful_signal_log_matches(self, pid, signum, signame, contents):
        self.assertRegex(
            contents,
            """\
timestamp: ([^\n]+)
process title: ([^\n]+)
sys\\.argv: ([^\n]+)
pid: {pid}
Signal {signum} \\({signame}\\) was raised\\. Exiting with failure\\.
""".format(
                pid=pid, signum=signum, signame=signame
            ),
        )
        # Ensure we write all output such as stderr and reporting files before closing any streams.
        self.assertNotIn("Exception message: I/O operation on closed file.", contents)

    @pytest.mark.skip(reason="flaky?")
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
                pid_specific_log_file, shared_log_file = self._get_log_file_paths(ctx.workdir, pid)
                self._assert_graceful_signal_log_matches(
                    pid, signum, signame, read_file(pid_specific_log_file)
                )
                self._assert_graceful_signal_log_matches(
                    pid, signum, signame, read_file(shared_log_file)
                )

    @pytest.mark.skip(reason="flaky?")
    def test_dumps_traceback_on_sigabrt(self):
        # SIGABRT sends a traceback to the log file for the current process thanks to
        # faulthandler.enable().
        with self.pantsd_successful_run_context() as ctx:
            ctx.runner(["help"])
            pid = ctx.checker.assert_started()
            os.kill(pid, signal.SIGABRT)

            time.sleep(5)

            # Check that the logs show an abort signal and the beginning of a traceback.
            pid_specific_log_file, shared_log_file = self._get_log_file_paths(ctx.workdir, pid)
            self.assertRegex(
                read_file(pid_specific_log_file),
                """\
Fatal Python error: Aborted

Thread [^\n]+ \\(most recent call first\\):
""",
            )
            # faulthandler.enable() only allows use of a single logging file at once for fatal tracebacks.
            self.assertEqual("", read_file(shared_log_file))

    @pytest.mark.skip(reason="flaky?")
    def test_prints_traceback_on_sigusr2(self):
        with self.pantsd_successful_run_context() as ctx:
            ctx.runner(["help"])
            pid = ctx.checker.assert_started()
            os.kill(pid, signal.SIGUSR2)

            time.sleep(5)

            ctx.checker.assert_running()
            self.assertRegex(
                read_file(os.path.join(ctx.workdir, "pantsd", "pantsd.log")),
                """\
Current thread [^\n]+ \\(most recent call first\\):
""",
            )

    def _lifecycle_stub_cmdline(self):
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
