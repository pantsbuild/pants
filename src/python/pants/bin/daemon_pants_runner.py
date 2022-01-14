# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import sys
import time
from contextlib import contextmanager
from threading import Lock
from typing import Dict, Tuple

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, ExitCode
from pants.bin.local_pants_runner import LocalPantsRunner
from pants.engine.environment import CompleteEnvironment
from pants.engine.internals.native_engine import PySessionCancellationLatch
from pants.init.logging import stdio_destination
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_core import PantsDaemonCore

logger = logging.getLogger(__name__)


class ExclusiveRequestTimeout(Exception):
    """Represents a timeout while waiting for another request to complete."""


class DaemonPantsRunner:
    """A RawFdRunner (callable) that will be called for each client request to Pantsd."""

    def __init__(self, core: PantsDaemonCore) -> None:
        super().__init__()
        self._core = core
        self._run_lock = Lock()

    @staticmethod
    def _send_stderr(stderr_fileno: int, msg: str) -> None:
        """Used to send stderr on a raw filehandle _before_ stdio replacement.

        TODO: This method will be removed as part of #7654.
        """
        with os.fdopen(stderr_fileno, mode="w", closefd=False) as stderr:
            print(msg, file=stderr, flush=True)

    @contextmanager
    def _one_run_at_a_time(
        self, stderr_fileno: int, cancellation_latch: PySessionCancellationLatch, timeout: float
    ):
        """Acquires exclusive access within the daemon.

        Periodically prints a message on the given stderr_fileno while exclusive access cannot be
        acquired.

        TODO: This method will be removed as part of #7654, so it currently polls the lock and
        cancellation latch rather than waiting for both of them asynchronously, which would be a bit
        cleaner.
        """

        render_timeout = 5
        should_poll_forever = timeout <= 0
        start = time.time()
        render_deadline = start + render_timeout
        deadline = None if should_poll_forever else start + timeout

        def should_keep_polling(now):
            return not cancellation_latch.is_cancelled() and (not deadline or deadline > now)

        acquired = self._run_lock.acquire(blocking=False)
        if not acquired:
            # If we don't acquire immediately, send an explanation.
            length = "forever" if should_poll_forever else f"up to {timeout} seconds"
            self._send_stderr(
                stderr_fileno,
                f"Another pants invocation is running. Will wait {length} for it to finish before giving up.\n"
                "If you don't want to wait for the first run to finish, please press Ctrl-C and run "
                "this command with PANTS_CONCURRENT=True in the environment.\n",
            )
        while True:
            now = time.time()
            if acquired:
                try:
                    yield
                    break
                finally:
                    self._run_lock.release()
            elif should_keep_polling(now):
                if now > render_deadline:
                    self._send_stderr(
                        stderr_fileno,
                        f"Waiting for invocation to finish (waited for {int(now - start)}s so far)...\n",
                    )
                    render_deadline = now + render_timeout
                acquired = self._run_lock.acquire(blocking=True, timeout=0.1)
            else:
                raise ExclusiveRequestTimeout(
                    "Timed out while waiting for another pants invocation to finish."
                )

    def single_daemonized_run(
        self,
        args: Tuple[str, ...],
        env: Dict[str, str],
        cancellation_latch: PySessionCancellationLatch,
    ) -> ExitCode:
        """Run a single daemonized run of Pants.

        All aspects of the `sys` global should already have been replaced in `__call__`, so this
        method should not need any special handling for the fact that it's running in a proxied
        environment.
        """

        try:
            logger.debug("Connected to pantsd")
            # Capture the client's start time, which we propagate here in order to get an accurate
            # view of total time.
            env_start_time = env.get("PANTSD_RUNTRACKER_CLIENT_START_TIME", None)
            if not env_start_time:
                # NB: We warn rather than erroring here because it eases use of non-Pants nailgun
                # clients for testing.
                logger.warning(
                    "No start time was reported by the client! Metrics may be inaccurate."
                )
            start_time = float(env_start_time) if env_start_time else time.time()

            options_bootstrapper = OptionsBootstrapper.create(
                env=env, args=args, allow_pantsrc=True
            )

            # Run using the pre-warmed Session.
            complete_env = CompleteEnvironment(env)
            scheduler, options_initializer = self._core.prepare(options_bootstrapper, complete_env)
            runner = LocalPantsRunner.create(
                complete_env,
                options_bootstrapper,
                scheduler=scheduler,
                options_initializer=options_initializer,
                cancellation_latch=cancellation_latch,
            )
            return runner.run(start_time)
        except Exception as e:
            logger.exception(e)
            return PANTS_FAILED_EXIT_CODE
        except KeyboardInterrupt:
            print("Interrupted by user.\n", file=sys.stderr)
            return PANTS_FAILED_EXIT_CODE

    def __call__(
        self,
        command: str,
        args: Tuple[str, ...],
        env: Dict[str, str],
        cancellation_latch: PySessionCancellationLatch,
        stdin_fileno: int,
        stdout_fileno: int,
        stderr_fileno: int,
    ) -> ExitCode:
        request_timeout = float(env.get("PANTSD_REQUEST_TIMEOUT_LIMIT", -1))
        # NB: Order matters: we acquire a lock before mutating either `sys.std*`, `os.environ`, etc.
        with self._one_run_at_a_time(
            stderr_fileno,
            cancellation_latch=cancellation_latch,
            timeout=request_timeout,
        ):
            # NB: `single_daemonized_run` implements exception handling, so only the most primitive
            # errors will escape this function, where they will be logged by the server.
            logger.info(f"handling request: `{' '.join(args)}`")
            try:
                with stdio_destination(
                    stdin_fileno=stdin_fileno,
                    stdout_fileno=stdout_fileno,
                    stderr_fileno=stderr_fileno,
                ):
                    return self.single_daemonized_run(((command,) + args), env, cancellation_latch)
            finally:
                logger.info(f"request completed: `{' '.join(args)}`")
