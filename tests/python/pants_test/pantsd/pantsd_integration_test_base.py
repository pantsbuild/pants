# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import os
import time
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

from colors import bold, cyan, magenta

from pants.pantsd.process_manager import ProcessManager
from pants.testutil.pants_integration_test import (
    kill_daemon,
    read_pantsd_log,
    run_pants_with_workdir,
)
from pants.util.collections import recursively_update
from pants.util.contextutil import temporary_dir


def banner(s):
    print(cyan("=" * 63))
    print(cyan(f"- {s} {('-' * (60 - len(s)))}"))
    print(cyan("=" * 63))


def attempts(
    msg: str,
    *,
    delay: float = 0.5,
    timeout: float = 60,
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
    pantsd_config: Dict[str, Any]


class PantsDaemonIntegrationTestBase(unittest.TestCase):
    use_pantsd = False  # We set our own ad-hoc pantsd configuration in most of these tests.

    @contextmanager
    def pantsd_test_context(
        self, *, log_level: str = "info", extra_config: Optional[Dict[str, Any]] = None
    ) -> Iterator[Tuple[str, Dict[str, Any], PantsDaemonMonitor]]:
        with temporary_dir(root_dir=os.getcwd()) as workdir_base:
            pid_dir = os.path.join(workdir_base, ".pids")
            workdir = os.path.join(workdir_base, ".workdir.pants.d")
            print(f"\npantsd log is {workdir}/pantsd/pantsd.log")
            pantsd_config = {
                "GLOBAL": {
                    "pantsd": True,
                    "level": log_level,
                    "pants_subprocessdir": pid_dir,
                }
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
                banner("BEGIN pantsd.log")
                for line in read_pantsd_log(workdir):
                    print(line)
                banner("END pantsd.log")

    @contextmanager
    def pantsd_successful_run_context(self, *args, **kwargs) -> Iterator[PantsdRunContext]:
        with self.pantsd_run_context(*args, success=True, **kwargs) as context:  # type: ignore[misc]
            yield context

    @contextmanager
    def pantsd_run_context(
        self,
        log_level: str = "info",
        extra_config: Optional[Dict[str, Any]] = None,
        extra_env: Optional[Dict[str, str]] = None,
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
        run = run_pants_with_workdir(
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
