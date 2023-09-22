# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import os
import time
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping

from colors import bold, cyan, magenta

from pants.pantsd.process_manager import ProcessManager
from pants.testutil.pants_integration_test import (
    PantsJoinHandle,
    PantsResult,
    kill_daemon,
    read_pants_log,
    run_pants,
    run_pants_with_workdir,
    run_pants_with_workdir_without_waiting,
)
from pants.util.collections import recursively_update
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import maybe_read_file


def banner(s):
    print(cyan("=" * 63))
    print(cyan(f"- {s} {('-' * (60 - len(s)))}"))
    print(cyan("=" * 63))


def attempts(
    msg: str,
    *,
    delay: float = 0.5,
    timeout: float = 30,
    backoff: float = 1.2,
) -> Iterator[None]:
    """A generator that yields a number of times before failing.

    A caller should break out of a loop on the generator in order to succeed.
    """
    count = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        count += 1
        yield
        time.sleep(delay)
        delay *= backoff
    raise AssertionError(f"After {count} attempts in {timeout} seconds: {msg}")


def launch_waiter(
    *, workdir: str, config: Mapping | None = None, cleanup_wait_time: int = 0
) -> tuple[PantsJoinHandle, int, int, str]:
    """Launch a process that will wait forever for a file to be created.

    Returns the pants client handle, the pid of the waiting process, the pid of a child of the
    waiting process, and the file to create to cause the waiting child to exit.
    """
    file_to_make = os.path.join(workdir, "some_magic_file")
    waiter_pid_file = os.path.join(workdir, "pid_file")
    child_pid_file = os.path.join(workdir, "child_pid_file")

    argv = [
        "run",
        "testprojects/src/python/coordinated_runs:waiter",
        "--",
        file_to_make,
        waiter_pid_file,
        child_pid_file,
        str(cleanup_wait_time),
    ]
    client_handle = run_pants_with_workdir_without_waiting(argv, workdir=workdir, config=config)
    waiter_pid = -1
    for _ in attempts("The waiter process should have written its pid."):
        waiter_pid_str = maybe_read_file(waiter_pid_file)
        child_pid_str = maybe_read_file(child_pid_file)
        if waiter_pid_str and child_pid_str:
            waiter_pid = int(waiter_pid_str)
            child_pid = int(child_pid_str)
            break
    return client_handle, waiter_pid, child_pid, file_to_make


class PantsDaemonMonitor(ProcessManager):
    def __init__(self, metadata_base_dir: str):
        super().__init__(name="pantsd", metadata_base_dir=metadata_base_dir)
        self._started = False

    def _log(self):
        print(magenta(f"PantsDaemonMonitor: pid is {self.pid} is_alive={self.is_alive()}"))

    def assert_started_and_stopped(self, timeout: int = 30) -> None:
        """Asserts that pantsd was alive (it wrote a pid file), but that it stops afterward."""
        self.await_pid(timeout)
        self._started = True
        self.assert_stopped()

    def assert_started(self, timeout=30):
        self.await_pid(timeout)
        self._started = True
        self._check_pantsd_is_alive()
        return self.pid

    def _check_pantsd_is_alive(self):
        self._log()
        assert (
            self._started
        ), "cannot assert that pantsd is running. Try calling assert_started before calling this method."
        assert self.is_alive(), "pantsd was not alive."
        return self.pid

    def current_memory_usage(self):
        """Return the current memory usage of the pantsd process (which must be running)

        :return: memory usage in bytes
        """
        self.assert_running()
        return self._as_process().memory_info()[0]

    def assert_running(self):
        if not self._started:
            return self.assert_started()
        else:
            return self._check_pantsd_is_alive()

    def assert_stopped(self):
        self._log()
        assert (
            self._started
        ), "cannot assert pantsd stoppage. Try calling assert_started before calling this method."
        for _ in attempts("pantsd should be stopped!"):
            if self.is_dead():
                break


@dataclass(frozen=True)
class PantsdRunContext:
    runner: Callable[..., Any]
    checker: PantsDaemonMonitor
    workdir: str
    pantsd_config: dict[str, Any]


class PantsDaemonIntegrationTestBase(unittest.TestCase):
    @staticmethod
    def run_pants(*args, **kwargs) -> PantsResult:
        # We set our own ad-hoc pantsd configuration in most of these tests.
        return run_pants(*args, **{**kwargs, **{"use_pantsd": False}})

    @staticmethod
    def run_pants_with_workdir(*args, **kwargs) -> PantsResult:
        # We set our own ad-hoc pantsd configuration in most of these tests.
        return run_pants_with_workdir(*args, **{**kwargs, **{"use_pantsd": False}})

    @staticmethod
    def run_pants_with_workdir_without_waiting(*args, **kwargs) -> PantsJoinHandle:
        # We set our own ad-hoc pantsd configuration in most of these tests.
        return run_pants_with_workdir_without_waiting(*args, **{**kwargs, **{"use_pantsd": False}})

    @contextmanager
    def pantsd_test_context(
        self, *, log_level: str = "info", extra_config: dict[str, Any] | None = None
    ) -> Iterator[tuple[str, dict[str, Any], PantsDaemonMonitor]]:
        with temporary_dir(root_dir=os.getcwd()) as dot_pants_dot_d:
            pid_dir = os.path.join(dot_pants_dot_d, "pids")
            workdir = os.path.join(dot_pants_dot_d, "workdir")
            print(f"\npantsd log is {workdir}/pantsd/pantsd.log")
            pantsd_config = {
                "GLOBAL": {
                    "pantsd": True,
                    "level": log_level,
                    "pants_subprocessdir": pid_dir,
                    "backend_packages": [
                        # Provide goals used by various tests.
                        "pants.backend.python",
                        "pants.backend.python.lint.flake8",
                    ],
                },
                "python": {
                    "interpreter_constraints": "['>=3.7,<3.10']",
                },
            }

            if extra_config:
                recursively_update(pantsd_config, extra_config)
            print(f">>> config: \n{pantsd_config}\n")

            checker = PantsDaemonMonitor(pid_dir)
            kill_daemon(pid_dir)
            try:
                yield workdir, pantsd_config, checker
                kill_daemon(pid_dir)
                checker.assert_stopped()
            finally:
                banner("BEGIN pants.log")
                for line in read_pants_log(workdir):
                    print(line)
                banner("END pants.log")

    @contextmanager
    def pantsd_successful_run_context(self, *args, **kwargs) -> Iterator[PantsdRunContext]:
        with self.pantsd_run_context(*args, success=True, **kwargs) as context:  # type: ignore[misc]
            yield context

    @contextmanager
    def pantsd_run_context(
        self,
        log_level: str = "info",
        extra_config: dict[str, Any] | None = None,
        extra_env: dict[str, str] | None = None,
        success: bool = True,
    ) -> Iterator[PantsdRunContext]:
        with self.pantsd_test_context(log_level=log_level, extra_config=extra_config) as (
            workdir,
            pantsd_config,
            checker,
        ):
            runner = functools.partial(
                self.assert_runner,
                workdir,
                pantsd_config,
                extra_env=extra_env,
                success=success,
            )
            yield PantsdRunContext(
                runner=runner, checker=checker, workdir=workdir, pantsd_config=pantsd_config
            )

    def _run_count(self, workdir):
        run_tracker_dir = os.path.join(workdir, "run-tracker")
        if os.path.isdir(run_tracker_dir):
            return len([f for f in os.listdir(run_tracker_dir) if f != "latest"])
        else:
            return 0

    def assert_runner(
        self,
        workdir: str,
        config,
        cmd,
        extra_config=None,
        extra_env=None,
        success=True,
        expected_runs: int = 1,
    ):
        combined_config = config.copy()
        recursively_update(combined_config, extra_config or {})
        print(
            bold(
                cyan(
                    "\nrunning: ./pants {} (config={}) (extra_env={})".format(
                        " ".join(cmd), combined_config, extra_env
                    )
                )
            )
        )
        run_count = self._run_count(workdir)
        start_time = time.time()
        run = self.run_pants_with_workdir(
            cmd, workdir=workdir, config=combined_config, extra_env=extra_env or {}
        )
        elapsed = time.time() - start_time
        print(bold(cyan(f"\ncompleted in {elapsed} seconds")))

        if success:
            run.assert_success()
        else:
            run.assert_failure()

        runs_created = self._run_count(workdir) - run_count
        self.assertEqual(
            runs_created,
            expected_runs,
            "Expected {} RunTracker run(s) to be created per pantsd run: was {}".format(
                expected_runs, runs_created
            ),
        )

        return run
