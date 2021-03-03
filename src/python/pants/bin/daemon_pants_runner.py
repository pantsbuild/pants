# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import sys
import time
from threading import Lock
from typing import Dict, Tuple

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, ExitCode
from pants.bin.local_pants_runner import LocalPantsRunner
from pants.engine.environment import CompleteEnvironment
from pants.engine.internals.native import RawFdRunner
from pants.engine.internals.native_engine import PySessionCancellationLatch
from pants.init.logging import stdio_destination
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_core import PantsDaemonCore

logger = logging.getLogger(__name__)


class ExclusiveRequestTimeout(Exception):
    """Represents a timeout while waiting for another request to complete."""


class DaemonPantsRunner(RawFdRunner):
    """A RawFdRunner (callable) that will be called for each client request to Pantsd."""

    def __init__(self, core: PantsDaemonCore) -> None:
        super().__init__()
        self._core = core
        self._run_lock = Lock()

    def single_daemonized_run(
        self,
        args: Tuple[str, ...],
        env: Dict[str, str],
        working_dir: str,
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
        working_directory: bytes,
        cancellation_latch: PySessionCancellationLatch,
        stdin_fileno: int,
        stdout_fileno: int,
        stderr_fileno: int,
    ) -> ExitCode:
        # NB: `single_daemonized_run` implements exception handling, so only the most primitive
        # errors will escape this function, where they will be logged by the server.
        logger.info(f"handling request: `{' '.join(args)}`")
        try:
            with stdio_destination(
                stdin_fileno=stdin_fileno,
                stdout_fileno=stdout_fileno,
                stderr_fileno=stderr_fileno,
            ):
                return self.single_daemonized_run(
                    ((command,) + args), env, working_directory.decode(), cancellation_latch
                )
        finally:
            logger.info(f"request completed: `{' '.join(args)}`")
