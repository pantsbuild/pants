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
from pants.engine.internals.native import Native, RawFdRunner
from pants.init.logging import (
    clear_logging_handlers,
    get_logging_handlers,
    set_logging_handlers,
    setup_logging,
)
from pants.init.util import clean_global_runtime_state
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_core import PantsDaemonCore
from pants.util.contextutil import argv_as, hermetic_environment_as, stdio_as

logger = logging.getLogger(__name__)


class ExclusiveRequestTimeout(Exception):
    """Represents a timeout while waiting for another request to complete."""


class DaemonPantsRunner(RawFdRunner):
    """A RawFdRunner (callable) that will be called for each client request to Pantsd."""

    def __init__(self, core: PantsDaemonCore) -> None:
        super().__init__()
        self._core = core
        self._run_lock = Lock()

    @staticmethod
    def _send_stderr(stderr_fd: int, msg: str) -> None:
        """Used to send stderr on a raw filehandle _before_ stdio replacement.

        After stdio replacement has happened via `stdio_as` (which mutates sys.std*, and thus cannot
        happen until the request lock has been acquired), sys.std* should be used directly.
        """
        with os.fdopen(stderr_fd, mode="w", closefd=False) as stderr:
            print(msg, file=stderr, flush=True)

    @contextmanager
    def _one_run_at_a_time(self, stderr_fd: int, timeout: float):
        """Acquires exclusive access within the daemon.

        Periodically prints a message on the given stderr_fd while exclusive access cannot be
        acquired.
        """

        should_poll_forever = timeout <= 0
        start = time.time()
        deadline = None if should_poll_forever else start + timeout

        def should_keep_polling(now):
            return not deadline or deadline > now

        acquired = self._run_lock.acquire(blocking=False)
        if not acquired:
            # If we don't acquire immediately, send an explanation.
            length = "forever" if should_poll_forever else "up to {} seconds".format(timeout)
            self._send_stderr(
                stderr_fd,
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
                self._send_stderr(
                    stderr_fd,
                    f"Waiting for invocation to finish (waited for {int(now - start)}s so far)...\n",
                )
                acquired = self._run_lock.acquire(blocking=True, timeout=5)
            else:
                raise ExclusiveRequestTimeout(
                    "Timed out while waiting for another pants invocation to finish."
                )

    @contextmanager
    def _stderr_logging(self, global_bootstrap_options):
        """Temporarily replaces existing handlers (ie, the pantsd handler) with a stderr handler.

        In the context of pantsd, there will be an existing handler for the pantsd log, which we
        temporarily replace. Making them additive would cause per-run logs to go to pantsd, which
        we don't want.

        TODO: It would be good to handle logging destinations entirely via the threadlocal state
        rather than via handler mutations.
        """
        handlers = get_logging_handlers()
        try:
            clear_logging_handlers()
            Native().override_thread_logging_destination_to_just_stderr()
            setup_logging(global_bootstrap_options, stderr_logging=True)
            yield
        finally:
            Native().override_thread_logging_destination_to_just_pantsd()
            set_logging_handlers(handlers)

    def single_daemonized_run(self, working_dir: str) -> ExitCode:
        """Run a single daemonized run of Pants.

        All aspects of the `sys` global should already have been replaced in `__call__`, so this
        method should not need any special handling for the fact that it's running in a proxied
        environment.
        """

        # Capture the client's start time, which we propagate here in order to get an accurate
        # view of total time.
        env_start_time = os.environ.get("PANTSD_RUNTRACKER_CLIENT_START_TIME", None)
        start_time = float(env_start_time) if env_start_time else time.time()

        # Clear global mutable state before entering `LocalPantsRunner`. Note that we use
        # `sys.argv` and `os.environ`, since they have been mutated to maintain the illusion
        # of a local run: once we allow for concurrent runs, this information should be
        # propagated down from the caller.
        #   see https://github.com/pantsbuild/pants/issues/7654
        clean_global_runtime_state()
        options_bootstrapper = OptionsBootstrapper.create(
            env=os.environ, args=sys.argv, allow_pantsrc=True
        )
        bootstrap_options = options_bootstrapper.bootstrap_options
        global_bootstrap_options = bootstrap_options.for_global_scope()

        # Run using the pre-warmed Session.
        with self._stderr_logging(global_bootstrap_options):
            try:
                scheduler = self._core.prepare_scheduler(options_bootstrapper)
                runner = LocalPantsRunner.create(
                    os.environ, options_bootstrapper, scheduler=scheduler
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
        working_directory: bytes,
        stdin_fd: int,
        stdout_fd: int,
        stderr_fd: int,
    ) -> ExitCode:
        request_timeout = float(env.get("PANTSD_REQUEST_TIMEOUT_LIMIT", -1))
        # NB: Order matters: we acquire a lock before mutating either `sys.std*`, `os.environ`, etc.
        with self._one_run_at_a_time(stderr_fd, timeout=request_timeout), stdio_as(
            stdin_fd=stdin_fd, stdout_fd=stdout_fd, stderr_fd=stderr_fd
        ), hermetic_environment_as(**env), argv_as((command,) + args):
            # NB: Run implements exception handling, so only the most primitive errors will escape
            # this function, where they will be logged to the pantsd.log by the server.
            logger.info(f"handling request: `{' '.join(args)}`")
            try:
                return self.single_daemonized_run(working_directory.decode())
            finally:
                logger.info(f"request completed: `{' '.join(args)}`")
