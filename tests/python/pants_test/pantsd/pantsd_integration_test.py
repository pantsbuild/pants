# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import os
import signal
import threading
import time
import unittest
from textwrap import dedent
from typing import Tuple

import psutil
import pytest

from pants.testutil.pants_integration_test import (
    PantsJoinHandle,
    read_pantsd_log,
    temporary_workdir,
)
from pants.util.contextutil import environment_as, temporary_dir, temporary_file
from pants.util.dirutil import (
    maybe_read_file,
    rm_rf,
    safe_file_dump,
    safe_mkdir,
    safe_open,
    safe_rmtree,
    touch,
)
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase, attempts


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


class TestPantsDaemonIntegration(PantsDaemonIntegrationTestBase):
    hermetic = False

    def test_pantsd_run(self):
        with self.pantsd_successful_run_context(log_level="debug") as ctx:
            ctx.runner(["list", "3rdparty::"])
            ctx.checker.assert_started()

            ctx.runner(["list", "3rdparty::"])
            ctx.checker.assert_running()

    def test_pantsd_broken_pipe(self):
        with self.pantsd_test_context() as (workdir, pantsd_config, checker):
            run = self.run_pants_with_workdir(
                "help | head -1", workdir=workdir, config=pantsd_config, shell=True
            )
            self.assertNotIn("broken pipe", run.stderr.lower())
            checker.assert_started()

    def test_pantsd_pantsd_runner_doesnt_die_after_failed_run(self):
        with self.pantsd_test_context() as (workdir, pantsd_config, checker):
            # Run target that throws an exception in pants.
            self.run_pants_with_workdir(
                ["lint", "testprojects/src/python/unicode/compilation_failure"],
                workdir=workdir,
                config=pantsd_config,
            ).assert_failure()
            checker.assert_started()

            # Assert pantsd is in a good functional state.
            self.run_pants_with_workdir(
                ["help"], workdir=workdir, config=pantsd_config
            ).assert_success()
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
            cmds = (["help"], ["--no-colors", "help"], ["help"])
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
            self.run_pants_with_workdir(["help"], workdir=workdir, config=config).assert_success()
            checker.assert_started()

            # And again with invalid scheduler-fingerprinted options that trigger a re-init.
            self.run_pants_with_workdir(
                ["--backend-packages=nonsensical", "help"], workdir=workdir, config=config
            ).assert_failure()
            checker.assert_stopped()

    def test_pantsd_aligned_output(self) -> None:
        # Set for pytest output display.
        self.maxDiff = None

        cmds = [["help", "goals"], ["help", "targets"], ["roots"]]

        non_daemon_runs = [self.run_pants(cmd) for cmd in cmds]

        with self.pantsd_successful_run_context() as ctx:
            daemon_runs = [ctx.runner(cmd) for cmd in cmds]
            ctx.checker.assert_started()

        for cmd, run in zip(cmds, daemon_runs):
            print(f"(cmd, run) = ({cmd}, {run.stdout}, {run.stderr_data})")
            self.assertNotEqual(run.stdout, "", f"Empty stdout for {cmd}")

        for run_pair in zip(non_daemon_runs, daemon_runs):
            non_daemon_stdout = run_pair[0].stdout
            daemon_stdout = run_pair[1].stdout

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
                    ["run", "testprojects/src/python/print_env", "--", EXPECTED_KEY]
                )
                ctx.checker.assert_running()

            self.assertEqual(EXPECTED_VALUE, "".join(result.stdout).strip())

    def test_pantsd_launch_env_var_is_not_inherited_by_pantsd_runner_children(self):
        with self.pantsd_test_context() as (workdir, pantsd_config, checker):
            with environment_as(NO_LEAKS="33"):
                self.run_pants_with_workdir(
                    ["help"], workdir=workdir, config=pantsd_config
                ).assert_success()
                checker.assert_started()

            self.run_pants_with_workdir(
                ["run", "testprojects/src/python/print_env", "--", "NO_LEAKS"],
                workdir=workdir,
                config=pantsd_config,
            ).assert_failure()
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
            safe_rmtree(subprocess_dir)

            ctx.checker.assert_stopped()

    def test_pantsd_pid_change(self):
        with self.pantsd_successful_run_context() as ctx:
            ctx.runner(["help"])
            ctx.checker.assert_started()

            # Let any fs events quiesce.
            time.sleep(10)

            ctx.checker.assert_running()
            subprocess_dir = ctx.pantsd_config["GLOBAL"]["pants_subprocessdir"]
            (pidpath,) = glob.glob(os.path.join(subprocess_dir, "*", "pantsd", "pid"))
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
            ctx.runner(cmd).assert_success()
            initial_memory_usage = ctx.checker.current_memory_usage()
            for _ in range(number_of_runs):
                ctx.runner(cmd).assert_success()
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
        test_path = "daemon_correctness_test_0001"
        test_build_file = os.path.join(test_path, "BUILD")
        test_src_file = os.path.join(test_path, "some_file.py")
        filedeps_cmd = ["--files-not-found-behavior=warn", "filedeps", test_path]

        try:
            with self.pantsd_successful_run_context() as ctx:
                safe_mkdir(test_path, clean=True)

                ctx.runner(["help"])
                ctx.checker.assert_started()

                safe_file_dump(
                    test_build_file, "python_library(sources=['some_non_existent_file.py'])"
                )
                non_existent_file = os.path.join(test_path, "some_non_existent_file.py")

                result = ctx.runner(filedeps_cmd)
                ctx.checker.assert_running()
                assert non_existent_file not in result.stdout

                safe_file_dump(test_build_file, "python_library(sources=['*.py'])")
                result = ctx.runner(filedeps_cmd)
                ctx.checker.assert_running()
                assert non_existent_file not in result.stdout

                safe_file_dump(test_src_file, "print('hello')\n")
                result = ctx.runner(filedeps_cmd)
                ctx.checker.assert_running()
                assert test_src_file in result.stdout
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
                workdir=workdir,
                config=config,
            )

            checker.assert_started()

            creator_handle = self.run_pants_with_workdir_without_waiting(
                ["run", "testprojects/src/python/coordinated_runs:creator", "--", file_to_make],
                workdir=workdir,
                config=config,
            )

            creator_handle.join().assert_success()
            waiter_handle.join().assert_success()

    def _launch_waiter(self, workdir: str, config) -> Tuple[PantsJoinHandle, int, str]:
        """Launch a process via pantsd that will wait forever for the a file to be created.

        Returns the pid of the pantsd client, the pid of the waiting child process, and the file to
        create to cause the waiting child to exit.
        """
        file_to_make = os.path.join(workdir, "some_magic_file")
        waiter_pid_file = os.path.join(workdir, "pid_file")

        argv = [
            "run",
            "testprojects/src/python/coordinated_runs:waiter",
            "--",
            file_to_make,
            waiter_pid_file,
        ]
        client_handle = self.run_pants_with_workdir_without_waiting(
            argv, workdir=workdir, config=config
        )
        for _ in attempts("The waiter process should have written its pid."):
            waiter_pid_str = maybe_read_file(waiter_pid_file)
            if waiter_pid_str:
                waiter_pid = int(waiter_pid_str)
                break
        return client_handle, waiter_pid, file_to_make

    def _assert_pantsd_keyboardinterrupt_signal(self, signum, regexps=[]):
        """Send a signal to the thin pailgun client and observe the error messaging.

        :param int signum: The signal to send.
        :param regexps: Assert that all of these regexps match somewhere in stderr.
        :type regexps: list of str
        """
        with self.pantsd_test_context() as (workdir, config, checker):
            client_handle, waiter_process_pid, _ = self._launch_waiter(workdir, config)
            client_pid = client_handle.process.pid
            waiter_process = psutil.Process(waiter_process_pid)

            assert waiter_process.is_running()
            checker.assert_started()

            # This should kill the client, which will cancel the run on the server, which will
            # kill the waiting process.
            os.kill(client_pid, signum)
            client_run = client_handle.join()
            client_run.assert_failure()

            for regexp in regexps:
                self.assertRegex(client_run.stderr, regexp)

            # pantsd should still be running, but the waiter process should have been killed.
            time.sleep(5)
            assert not waiter_process.is_running()
            checker.assert_running()

    def test_pantsd_sigint(self):
        self._assert_pantsd_keyboardinterrupt_signal(
            signal.SIGINT,
            regexps=["Interrupted by user."],
        )

    def test_sigint_kills_request_waiting_for_lock(self):
        """Test that, when a pailgun request is blocked waiting for another one to end, sending
        SIGINT to the blocked run will kill it."""
        config = {"GLOBAL": {"pantsd_timeout_when_multiple_invocations": -1, "level": "debug"}}
        with self.pantsd_test_context(extra_config=config) as (workdir, config, checker):
            # Run a process that will wait forever.
            first_run_handle, _, file_to_create = self._launch_waiter(workdir, config)

            checker.assert_started()
            checker.assert_running()

            # And another that will block on the first.
            blocking_run_handle = self.run_pants_with_workdir_without_waiting(
                command=["goals"], workdir=workdir, config=config
            )

            # Block until the second request is waiting for the lock.
            time.sleep(10)

            # Sends SIGINT to the run that is waiting.
            blocking_run_client_pid = blocking_run_handle.process.pid
            os.kill(blocking_run_client_pid, signal.SIGINT)
            blocking_run_handle.join()

            # Check that pantsd is still serving the other request.
            checker.assert_running()

            # Exit the second run by writing the file it is waiting for, and confirm that it
            # exited, and that pantsd is still running.
            safe_file_dump(file_to_create, "content!")
            result = first_run_handle.join()
            result.assert_success()
            checker.assert_running()

    def test_pantsd_unicode_environment(self):
        with self.pantsd_successful_run_context(extra_env={"XXX": "¡"}) as ctx:
            result = ctx.runner(["help"])
            ctx.checker.assert_started()
            result.assert_success()

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
                    result.assert_success()
                    expected_targets = {f"{directory}:{target}" for target in ("A", "B")}
                    self.assertEqual(expected_targets, set(result.stdout.strip().split("\n")))

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
        with temporary_workdir() as workdir:
            pants_run = self.run_pants_with_workdir(
                ["help", "goals"], workdir=workdir, config=config
            )
            pants_run.assert_success()
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
            result.assert_failure()
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
