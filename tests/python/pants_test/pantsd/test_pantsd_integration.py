# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import datetime
import os
import re
import signal
import threading
import time
import unittest
from textwrap import dedent

import pytest

from pants.testutil.pants_run_integration_test import read_pantsd_log
from pants.testutil.process_test_util import no_lingering_process_by_command
from pants.util.contextutil import environment_as, temporary_dir, temporary_file
from pants.util.dirutil import rm_rf, safe_file_dump, safe_mkdir, safe_open, touch
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase


def launch_file_toucher(f):
    """Launch a loop to touch the given file, and return a function to call to stop and join it."""
    if not os.path.isfile(f):
        raise AssertionError("Refusing to touch a non-file.")

    halt = threading.Event()

    def file_toucher():
        while not halt.isSet():
            touch(f)
            time.sleep(1)

    thread = threading.Thread(target=file_toucher)
    thread.daemon = True
    thread.start()

    def join():
        halt.set()
        thread.join(timeout=10)

    return join


@pytest.mark.skip(reason="Takes too long and flaky")
class TestPantsDaemonIntegration(PantsDaemonIntegrationTestBase):
    def test_pantsd_run(self):
        with self.pantsd_successful_run_context(log_level="debug") as ctx:
            ctx.runner(["list", "3rdparty::"])
            ctx.checker.assert_started()

            ctx.runner(["list", "3rdparty::"])
            ctx.checker.assert_running()

    def test_pantsd_broken_pipe(self):
        with self.pantsd_test_context() as (workdir, pantsd_config, checker):
            run = self.run_pants_with_workdir("help | head -1", workdir, pantsd_config, shell=True)
            self.assertNotIn("broken pipe", run.stderr_data.lower())
            checker.assert_started()

    def test_pantsd_pantsd_runner_doesnt_die_after_failed_run(self):
        # Check for no stray pantsd processes.
        with no_lingering_process_by_command("pantsd"):
            with self.pantsd_test_context() as (workdir, pantsd_config, checker):
                # Run target that throws an exception in pants.
                self.assert_failure(
                    self.run_pants_with_workdir(
                        [
                            "--no-v1",
                            "--v2",
                            "lint",
                            "testprojects/src/python/unicode/compilation_failure",
                        ],
                        workdir,
                        pantsd_config,
                    )
                )
                checker.assert_started()

                # Assert pantsd is in a good functional state.
                self.assert_success(
                    self.run_pants_with_workdir(["--no-v1", "--v2", "help"], workdir, pantsd_config)
                )
                checker.assert_running()

    def test_pantsd_lifecycle_invalidation(self):
        """Run with different values of daemon=True options, which should trigger restarts."""
        with self.pantsd_successful_run_context() as ctx:
            last_pid = None
            for idx in range(3):
                # Run with a different value of a daemon=True option in each iteration.
                ctx.runner([f"--pantsd-invalidation-globs=ridiculous{idx}", "help"])
                next_pid = ctx.checker.assert_started()
                if last_pid is not None:
                    self.assertNotEqual(last_pid, next_pid)
                last_pid = next_pid

    def test_pantsd_lifecycle_non_invalidation(self):
        with self.pantsd_successful_run_context() as ctx:
            cmds = (["-q", "help"], ["--no-colors", "help"], ["help"])
            last_pid = None
            for cmd in cmds:
                # Run with a CLI flag.
                ctx.runner(cmd)
                next_pid = ctx.checker.assert_started()
                if last_pid is not None:
                    self.assertEqual(last_pid, next_pid)
                last_pid = next_pid

    def test_pantsd_lifecycle_non_invalidation_on_config_string(self):
        with temporary_dir() as dist_dir_root, temporary_dir() as config_dir:
            # Create a variety of config files that change an option that does _not_ affect the
            # daemon's fingerprint (only the Scheduler's), and confirm that it stays up.
            config_files = [
                os.path.abspath(os.path.join(config_dir, f"pants.{i}.toml")) for i in range(3)
            ]
            for idx, config_file in enumerate(config_files):
                print(f"writing {config_file}")
                with open(config_file, "w") as fh:
                    fh.write(
                        f"""[GLOBAL]\npants_distdir = "{os.path.join(dist_dir_root, str(idx))}"\n"""
                    )

            with self.pantsd_successful_run_context() as ctx:
                cmds = [[f"--pants-config-files={f}", "help"] for f in config_files]
                last_pid = None
                for cmd in cmds:
                    ctx.runner(cmd)
                    next_pid = ctx.checker.assert_started()
                    if last_pid is not None:
                        self.assertEqual(last_pid, next_pid)
                    last_pid = next_pid

    def test_pantsd_lifecycle_shutdown_for_broken_scheduler(self):
        with self.pantsd_test_context() as (workdir, config, checker):
            # Run with valid options.
            self.assert_success(self.run_pants_with_workdir(["help"], workdir, config))
            checker.assert_started()

            # And again with invalid scheduler-fingerprinted options that trigger a re-init.
            self.assert_failure(
                self.run_pants_with_workdir(
                    ["--backend-packages=nonsensical", "help"], workdir, config
                )
            )
            checker.assert_stopped()

    def test_pantsd_aligned_output(self) -> None:
        # Set for pytest output display.
        self.maxDiff = None

        cmds = [["goals"], ["help"], ["targets"], ["roots"]]

        non_daemon_runs = [self.run_pants(cmd) for cmd in cmds]

        with self.pantsd_successful_run_context() as ctx:
            daemon_runs = [ctx.runner(cmd) for cmd in cmds]
            ctx.checker.assert_started()

        for cmd, run in zip(cmds, daemon_runs):
            print(f"(cmd, run) = ({cmd}, {run.stdout_data}, {run.stderr_data})")
            self.assertNotEqual(run.stdout_data, "", f"Empty stdout for {cmd}")

        for run_pair in zip(non_daemon_runs, daemon_runs):
            non_daemon_stdout = run_pair[0].stdout_data
            daemon_stdout = run_pair[1].stdout_data

            for line_pair in zip(non_daemon_stdout.splitlines(), daemon_stdout.splitlines()):
                assert line_pair[0] == line_pair[1]

    @unittest.skip("flaky: https://github.com/pantsbuild/pants/issues/7622")
    def test_pantsd_filesystem_invalidation(self):
        """Runs with pantsd enabled, in a loop, while another thread invalidates files."""
        with self.pantsd_successful_run_context() as ctx:
            cmd = ["list", "::"]
            ctx.runner(cmd)
            ctx.checker.assert_started()

            # Launch a separate thread to poke files in 3rdparty.
            join = launch_file_toucher("3rdparty/jvm/com/google/auto/value/BUILD")

            # Repeatedly re-list 3rdparty while the file is being invalidated.
            for _ in range(0, 16):
                ctx.runner(cmd)
                ctx.checker.assert_running()

            join()

    def test_pantsd_client_env_var_is_inherited_by_pantsd_runner_children(self):
        EXPECTED_KEY = "TEST_ENV_VAR_FOR_PANTSD_INTEGRATION_TEST"
        EXPECTED_VALUE = "333"
        with self.pantsd_successful_run_context() as ctx:
            # First, launch the daemon without any local env vars set.
            ctx.runner(["help"])
            ctx.checker.assert_started()

            # Then, set an env var on the secondary call.
            # We additionally set the `HERMETIC_ENV` env var to allow the integration test harness
            # to pass this variable through.
            env = {
                EXPECTED_KEY: EXPECTED_VALUE,
                "HERMETIC_ENV": EXPECTED_KEY,
            }
            with environment_as(**env):
                result = ctx.runner(
                    ["-q", "run", "testprojects/src/python/print_env", "--", EXPECTED_KEY]
                )
                ctx.checker.assert_running()

            self.assertEqual(EXPECTED_VALUE, "".join(result.stdout_data).strip())

    def test_pantsd_launch_env_var_is_not_inherited_by_pantsd_runner_children(self):
        with self.pantsd_test_context() as (workdir, pantsd_config, checker):
            with environment_as(NO_LEAKS="33"):
                self.assert_success(self.run_pants_with_workdir(["help"], workdir, pantsd_config))
                checker.assert_started()

            self.assert_failure(
                self.run_pants_with_workdir(
                    ["-q", "run", "testprojects/src/python/print_env", "--", "NO_LEAKS"],
                    workdir,
                    pantsd_config,
                )
            )
            checker.assert_running()

    def test_pantsd_touching_a_file_does_not_restart_daemon(self):
        test_file = "testprojects/src/python/print_env/main.py"
        config = {
            "GLOBAL": {"pantsd_invalidation_globs": '["testprojects/src/python/print_env/*"]'}
        }
        with self.pantsd_successful_run_context(extra_config=config) as ctx:
            ctx.runner(["help"])
            ctx.checker.assert_started()

            # Let any fs events quiesce.
            time.sleep(5)

            ctx.checker.assert_running()

            touch(test_file)
            # Permit ample time for the async file event propagate in CI.
            time.sleep(10)
            ctx.checker.assert_running()

    def test_pantsd_invalidation_file_tracking(self):
        test_dir = "testprojects/src/python/print_env"
        config = {"GLOBAL": {"pantsd_invalidation_globs": f'["{test_dir}/*"]'}}
        with self.pantsd_successful_run_context(extra_config=config) as ctx:
            ctx.runner(["help"])
            ctx.checker.assert_started()

            # Let any fs events quiesce.
            time.sleep(5)
            ctx.checker.assert_running()

            def full_pantsd_log():
                return "\n".join(read_pantsd_log(ctx.workdir))

            # Create a new file in test_dir
            with temporary_file(suffix=".py", binary_mode=False, root_dir=test_dir) as temp_f:
                temp_f.write("import that\n")
                temp_f.close()

                ctx.checker.assert_stopped()

            self.assertIn("saw filesystem changes covered by invalidation globs", full_pantsd_log())

    def test_pantsd_invalidation_pants_toml_file(self):
        # Test tmp_pants_toml (--pants-config-files=$tmp_pants_toml)'s removal
        tmp_pants_toml = os.path.abspath("testprojects/test_pants.toml")

        # Create tmp_pants_toml file
        with safe_open(tmp_pants_toml, "w") as f:
            f.write("[DEFAULT]\n")

        with self.pantsd_successful_run_context() as ctx:
            ctx.runner([f"--pants-config-files={tmp_pants_toml}", "help"])
            ctx.checker.assert_started()
            time.sleep(10)

            # Delete tmp_pants_toml
            os.unlink(tmp_pants_toml)
            ctx.checker.assert_stopped()

    def test_pantsd_pid_deleted(self):
        with self.pantsd_successful_run_context() as ctx:
            ctx.runner(["help"])
            ctx.checker.assert_started()

            # Let any fs events quiesce.
            time.sleep(10)

            ctx.checker.assert_running()
            subprocess_dir = ctx.pantsd_config["GLOBAL"]["pants_subprocessdir"]
            os.unlink(os.path.join(subprocess_dir, "pantsd", "pid"))

            ctx.checker.assert_stopped()

    def test_pantsd_pid_change(self):
        with self.pantsd_successful_run_context() as ctx:
            ctx.runner(["help"])
            ctx.checker.assert_started()

            # Let any fs events quiesce.
            time.sleep(10)

            ctx.checker.assert_running()
            subprocess_dir = ctx.pantsd_config["GLOBAL"]["pants_subprocessdir"]
            pidpath = os.path.join(subprocess_dir, "pantsd", "pid")
            with open(pidpath, "w") as f:
                f.write("9")

            ctx.checker.assert_stopped()

            # Remove the pidfile so that the teardown script doesn't try to kill process 9.
            os.unlink(pidpath)

    @pytest.mark.skip(reason="flaky: https://github.com/pantsbuild/pants/issues/8193")
    def test_pantsd_memory_usage(self):
        """Validates that after N runs, memory usage has increased by no more than X percent."""
        number_of_runs = 10
        max_memory_increase_fraction = 0.40  # TODO https://github.com/pantsbuild/pants/issues/7647
        with self.pantsd_successful_run_context() as ctx:
            # NB: This doesn't actually run against all testprojects, only those that are in the chroot,
            # i.e. explicitly declared in this test file's BUILD.
            cmd = ["list", "testprojects::"]
            self.assert_success(ctx.runner(cmd))
            initial_memory_usage = ctx.checker.current_memory_usage()
            for _ in range(number_of_runs):
                self.assert_success(ctx.runner(cmd))
                ctx.checker.assert_running()

            final_memory_usage = ctx.checker.current_memory_usage()
            self.assertTrue(
                initial_memory_usage <= final_memory_usage,
                "Memory usage inverted unexpectedly: {} > {}".format(
                    initial_memory_usage, final_memory_usage
                ),
            )

            increase_fraction = (float(final_memory_usage) / initial_memory_usage) - 1.0
            self.assertTrue(
                increase_fraction <= max_memory_increase_fraction,
                "Memory usage increased more than expected: {} -> {}: {} actual increase (expected < {})".format(
                    initial_memory_usage,
                    final_memory_usage,
                    increase_fraction,
                    max_memory_increase_fraction,
                ),
            )

    def test_pantsd_max_memory_usage(self):
        """Validates that the max_memory_usage setting is respected."""
        # We set a very, very low max memory usage, which forces pantsd to restart immediately.
        max_memory_usage_bytes = 130
        with self.pantsd_successful_run_context() as ctx:
            # TODO: We run the command, but we expect it to race pantsd shutting down, so we don't
            # assert success. https://github.com/pantsbuild/pants/issues/8200 will address waiting
            # until after the current command completes to invalidate the scheduler, at which point
            # we can assert success here.
            ctx.runner(
                [f"--pantsd-max-memory-usage={max_memory_usage_bytes}", "list", "testprojects::"]
            )

            # Assert that a pid file is written, but that the server stops afterward.
            ctx.checker.assert_started_and_stopped()

    def test_pantsd_invalidation_stale_sources(self):
        test_path = "tests/python/pants_test/daemon_correctness_test_0001"
        test_build_file = os.path.join(test_path, "BUILD")
        test_src_file = os.path.join(test_path, "some_file.py")
        has_source_root_regex = r'"source_root": ".*/{}"'.format(test_path)
        export_cmd = ["--files-not-found-behavior=warn", "export", test_path]

        try:
            with self.pantsd_successful_run_context() as ctx:
                safe_mkdir(test_path, clean=True)

                ctx.runner(["help"])
                ctx.checker.assert_started()

                safe_file_dump(
                    test_build_file, "python_library(sources=['some_non_existent_file.py'])"
                )
                result = ctx.runner(export_cmd)
                ctx.checker.assert_running()
                self.assertNotRegex(result.stdout_data, has_source_root_regex)

                safe_file_dump(test_build_file, "python_library(sources=['*.py'])")
                result = ctx.runner(export_cmd)
                ctx.checker.assert_running()
                self.assertNotRegex(result.stdout_data, has_source_root_regex)

                safe_file_dump(test_src_file, "import this\n")
                result = ctx.runner(export_cmd)
                ctx.checker.assert_running()
                self.assertRegex(result.stdout_data, has_source_root_regex)
        finally:
            rm_rf(test_path)

    @unittest.skip("TODO https://github.com/pantsbuild/pants/issues/7654")
    def test_pantsd_parse_exception_success(self):
        # This test covers the case described in #6426, where a run that is failing fast due to an
        # exception can race other completing work. We expect all runs to fail due to the error
        # that has been introduced, but none of them should hang.
        test_path = "testprojects/3rdparty/this_is_definitely_not_a_valid_directory"
        test_build_file = os.path.join(test_path, "BUILD")
        invalid_symbol = "this_is_definitely_not_a_valid_symbol"

        try:
            safe_mkdir(test_path, clean=True)
            safe_file_dump(test_build_file, f"{invalid_symbol}()")
            for _ in range(3):
                with self.pantsd_run_context(success=False) as ctx:
                    result = ctx.runner(["list", "testprojects::"])
                    ctx.checker.assert_started()
                    self.assertIn(invalid_symbol, result.stderr_data)
        finally:
            rm_rf(test_path)

    @unittest.skip("TODO https://github.com/pantsbuild/pants/issues/7654")
    def test_pantsd_multiple_parallel_runs(self):
        with self.pantsd_test_context() as (workdir, config, checker):
            file_to_make = os.path.join(workdir, "some_magic_file")
            waiter_handle = self.run_pants_with_workdir_without_waiting(
                ["run", "testprojects/src/python/coordinated_runs:waiter", "--", file_to_make],
                workdir,
                config,
            )

            checker.assert_started()
            checker.assert_pantsd_runner_started(waiter_handle.process.pid)

            creator_handle = self.run_pants_with_workdir_without_waiting(
                ["run", "testprojects/src/python/coordinated_runs:creator", "--", file_to_make],
                workdir,
                config,
            )

            self.assert_success(creator_handle.join())
            self.assert_success(waiter_handle.join())

    def _assert_pantsd_keyboardinterrupt_signal(self, signum, regexps=[], quit_timeout=None):
        """Send a signal to the thin pailgun client and observe the error messaging.

        :param int signum: The signal to send.
        :param regexps: Assert that all of these regexps match somewhere in stderr.
        :type regexps: list of str
        :param float quit_timeout: The duration of time to wait for the pailgun client to flush all of
                                   its output and die after being killed.
        """
        # TODO: This tests that pantsd processes actually die after the thin client receives the
        # specified signal.
        with self.pantsd_test_context() as (workdir, config, checker):
            # Launch a run that will wait for a file to be created (but do not create that file).
            file_to_make = os.path.join(workdir, "some_magic_file")

            if quit_timeout is not None:
                timeout_args = [f"--pantsd-pailgun-quit-timeout={quit_timeout}"]
            else:
                timeout_args = []
            argv = timeout_args + [
                "run",
                "testprojects/src/python/coordinated_runs:waiter",
                "--",
                file_to_make,
            ]
            waiter_handle = self.run_pants_with_workdir_without_waiting(argv, workdir, config)
            client_pid = waiter_handle.process.pid

            checker.assert_started()
            checker.assert_pantsd_runner_started(client_pid)

            # Get all the pantsd processes while they're still around.
            pantsd_runner_processes = checker.runner_process_context.current_processes()
            # This should kill the pantsd processes through the RemotePantsRunner signal handler.
            os.kill(client_pid, signum)
            waiter_run = waiter_handle.join()
            self.assert_failure(waiter_run)

            for regexp in regexps:
                self.assertRegex(waiter_run.stderr_data, regexp)

            time.sleep(1)
            for proc in pantsd_runner_processes:
                # TODO: we could be checking the return codes of the subprocesses, but psutil is currently
                # limited on non-Windows hosts -- see https://psutil.readthedocs.io/en/latest/#processes.
                # The pantsd processes should be dead, and they should have exited with 1.
                self.assertFalse(proc.is_running())

    @unittest.skip("flaky: https://github.com/pantsbuild/pants/issues/7554")
    def test_pantsd_sigterm(self):
        self._assert_pantsd_keyboardinterrupt_signal(
            signal.SIGTERM,
            regexps=[
                "\\[INFO\\] Sending SIGTERM to pantsd with pid [0-9]+, waiting up to 5\\.0 seconds before sending SIGKILL\\.\\.\\.",
                re.escape(
                    "\nSignal {signum} (SIGTERM) was raised. Exiting with failure.\n".format(
                        signum=signal.SIGTERM
                    )
                ),
                """
Interrupted by user:
Interrupted by user over pailgun client!
$""",
            ],
        )

    @unittest.skip("flaky: https://github.com/pantsbuild/pants/issues/7572")
    def test_pantsd_sigquit(self):
        self._assert_pantsd_keyboardinterrupt_signal(
            signal.SIGQUIT,
            regexps=[
                "\\[INFO\\] Sending SIGQUIT to pantsd with pid [0-9]+, waiting up to 5\\.0 seconds before sending SIGKILL\\.\\.\\.",
                re.escape(
                    "\nSignal {signum} (SIGQUIT) was raised. Exiting with failure.\n".format(
                        signum=signal.SIGQUIT
                    )
                ),
                """
Interrupted by user:
Interrupted by user over pailgun client!
$""",
            ],
        )

    @unittest.skip("flaky: https://github.com/pantsbuild/pants/issues/7547")
    def test_pantsd_sigint(self):
        self._assert_pantsd_keyboardinterrupt_signal(
            signal.SIGINT,
            regexps=[
                """\
\\[INFO\\] Sending SIGINT to pantsd with pid [0-9]+, waiting up to 5\\.0 seconds before sending SIGKILL\\.\\.\\.
Interrupted by user.
Interrupted by user:
Interrupted by user over pailgun client!
$"""
            ],
        )

    @unittest.skip("flaky: https://github.com/pantsbuild/pants/issues/7457")
    def test_signal_pailgun_stream_timeout(self):
        # NB: The actual timestamp has the date and time at sub-second granularity. The date is just
        # used here since that is known in advance in order to assert that the timestamp is well-formed.
        today = datetime.date.today().isoformat()
        self._assert_pantsd_keyboardinterrupt_signal(
            signal.SIGINT,
            regexps=[
                """\
\\[INFO\\] Sending SIGINT to pantsd with pid [0-9]+, waiting up to 0\\.01 seconds before sending SIGKILL\\.\\.\\.
Interrupted by user\\.
[^ ]* \\[WARN\\] timed out when attempting to gracefully shut down the remote client executing \
"'pantsd.*'"\\. sending SIGKILL to the remote client at pid: [0-9]+\\. message: iterating \
over bytes from nailgun timed out with timeout interval 0\\.01 starting at {today}T[^\n]+, \
overtime seconds: [^\n]+
Interrupted by user:
Interrupted by user over pailgun client!
""".format(
                    today=re.escape(today)
                )
            ],
            # NB: Make the timeout very small to ensure the warning message will reliably occur in CI!
            quit_timeout=1e-6,
        )

    @unittest.skip(
        reason="This started consistently hanging on Jan. 13, 2020 for some unknown reason."
    )
    def test_sigint_kills_request_waiting_for_lock(self):
        """Test that, when a pailgun request is blocked waiting for another one to end, sending
        SIGINT to the blocked run will kill it.

        Regression test for issue: #7920
        """
        config = {"GLOBAL": {"pantsd_timeout_when_multiple_invocations": -1, "level": "debug"}}
        with self.pantsd_test_context(extra_config=config) as (workdir, config, checker):
            # Run a repl, so that any other run waiting to acquire the daemon lock waits forever.
            first_run_handle = self.run_pants_with_workdir_without_waiting(
                command=["repl", "examples/src/python/example/hello::"],
                workdir=workdir,
                config=config,
            )
            checker.assert_started()
            checker.assert_running()

            blocking_run_handle = self.run_pants_with_workdir_without_waiting(
                command=["goals"], workdir=workdir, config=config
            )

            # Block until the second request is waiting for the lock.
            blocked = True
            while blocked:
                log = "\n".join(read_pantsd_log(workdir))
                if "didn't acquire the lock on the first try, polling." in log:
                    blocked = False
                # NB: This sleep is totally deterministic, it's just so that we don't spend too many cycles
                # busy waiting.
                time.sleep(0.1)

            # Sends SIGINT to the run that is waiting.
            blocking_run_client_pid = blocking_run_handle.process.pid
            os.kill(blocking_run_client_pid, signal.SIGINT)
            blocking_run_handle.join()

            # Check that pantsd is still serving the other request.
            checker.assert_running()

            # Send exit() to the repl, and exit it.
            result = first_run_handle.join(stdin_data="exit()")
            self.assert_success(result)
            checker.assert_running()

    def test_pantsd_unicode_environment(self):
        with self.pantsd_successful_run_context(extra_env={"XXX": "¡"},) as ctx:
            result = ctx.runner(["help"])
            ctx.checker.assert_started()
            self.assert_success(result)

    # This is a regression test for a bug where we would incorrectly detect a cycle if two targets swapped their
    # dependency relationship (#7404).
    def test_dependencies_swap(self):
        template = dedent(
            """
            python_library(
              name = 'A',
              source = 'A.py',
              {a_deps}
            )

            python_library(
              name = 'B',
              source = 'B.py',
              {b_deps}
            )
            """
        )
        with self.pantsd_successful_run_context() as ctx:
            with temporary_dir(".") as directory:
                safe_file_dump(os.path.join(directory, "A.py"), mode="w")
                safe_file_dump(os.path.join(directory, "B.py"), mode="w")

                if directory.startswith("./"):
                    directory = directory[2:]

                def list_and_verify():
                    result = ctx.runner(["list", f"{directory}:"])
                    ctx.checker.assert_started()
                    self.assert_success(result)
                    expected_targets = {f"{directory}:{target}" for target in ("A", "B")}
                    self.assertEqual(expected_targets, set(result.stdout_data.strip().split("\n")))

                with open(os.path.join(directory, "BUILD"), "w") as f:
                    f.write(template.format(a_deps='dependencies = [":B"],', b_deps=""))
                list_and_verify()

                with open(os.path.join(directory, "BUILD"), "w") as f:
                    f.write(template.format(a_deps="", b_deps='dependencies = [":A"],'))
                list_and_verify()

    def test_concurrent_overrides_pantsd(self):
        """Tests that the --concurrent flag overrides the --pantsd flag, because we don't allow
        concurrent runs under pantsd."""
        config = {"GLOBAL": {"concurrent": True, "pantsd": True}}
        with self.temporary_workdir() as workdir:
            pants_run = self.run_pants_with_workdir(["goals"], workdir=workdir, config=config)
            self.assert_success(pants_run)
            # TODO migrate to pathlib when we cut 1.18.x
            pantsd_log_location = os.path.join(workdir, "pantsd", "pantsd.log")
            self.assertFalse(os.path.exists(pantsd_log_location))

    def test_unhandled_exceptions_only_log_exceptions_once(self):
        """Tests that the unhandled exceptions triggered by LocalPantsRunner instances don't
        manifest as a PantsRunFinishedWithFailureException.

        That is, that we unset the global Exiter override set by LocalPantsRunner before we try to log the exception.

        This is a regression test for the most glaring case of https://github.com/pantsbuild/pants/issues/7597.
        """
        with self.pantsd_run_context(success=False) as ctx:
            result = ctx.runner(["run", "testprojects/src/python/bad_requirements:use_badreq"])
            ctx.checker.assert_running()
            self.assert_failure(result)
            # Assert that the desired exception has been triggered once.
            self.assertRegex(result.stderr_data, r"ERROR:.*badreq==99.99.99")
            # Assert that it has only been triggered once.
            self.assertNotIn(
                "During handling of the above exception, another exception occurred:",
                result.stderr_data,
            )
            self.assertNotIn(
                "pants.bin.daemon_pants_runner._PantsRunFinishedWithFailureException: Terminated with 1",
                result.stderr_data,
            )

    def test_inner_runs_dont_deadlock(self):
        """Create a pantsd run that calls testprojects/src/python/nested_runs with the appropriate
        bootstrap options to avoid restarting pantsd.

        Regression test for issue https://github.com/pantsbuild/pants/issues/7881
        When a run under pantsd calls pants with pantsd inside it, the inner run will time out
        waiting for the outer run to end.

        NB: testprojects/src/python/nested_runs assumes that the pants.toml file is in ${workdir}/pants.toml
        """
        config = {"GLOBAL": {"pantsd_timeout_when_multiple_invocations": 1}}
        with self.pantsd_successful_run_context(extra_config=config) as ctx:
            result = ctx.runner(
                ["run", "testprojects/src/python/nested_runs", "--", ctx.workdir], expected_runs=2
            )
            ctx.checker.assert_started()
            self.assert_success(result)
            self.assertNotIn("Another pants invocation is running", result.stderr_data)
