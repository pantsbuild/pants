# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Dict, Iterator, List, Mapping, Optional, Tuple

from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, ExitCode, Exiter
from pants.bin.local_pants_runner import LocalPantsRunner
from pants.engine.internals.native import RawFdRunner
from pants.engine.unions import UnionMembership
from pants.help.help_printer import HelpPrinter
from pants.init.specs_calculator import SpecsCalculator
from pants.init.util import clean_global_runtime_state
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.service.scheduler_service import SchedulerService
from pants.util.contextutil import argv_as, hermetic_environment_as, stdio_as
from pants.util.socket import teardown_socket

logger = logging.getLogger(__name__)


class ExclusiveRequestTimeout(Exception):
    """Represents a timeout while waiting for another request to complete."""


class DaemonPantsRunner(RawFdRunner):
    """A RawFdRunner (callable) that will be called for each client request to Pantsd."""

    def __init__(self, scheduler_service: SchedulerService):
        super().__init__()
        self._scheduler_service = scheduler_service
        self._run_lock = Lock()

    @staticmethod
    def _send_stderr(stderr_fd: int, msg: str):
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

    def _run(self, working_dir: str) -> int:
        """Run a single daemonized run of Pants.

        All aspects of the `sys` global should already have been replaced in `__call__`, so this
        method should not need any special handling for the fact that it's running in a proxied
        environment.
        """

        exit_code = PANTS_SUCCEEDED_EXIT_CODE
        try:
            if working_dir != os.getcwd():
                # This is likely an implementation error in the client (which we control).
                raise Exception(
                    "Running in a directory other than the build root is not currently supported.\n"
                    f"client in: {working_dir}\n"
                    f"server in: {os.getcwd()}"
                )

            # Clean global state.
            clean_global_runtime_state(reset_subsystem=True)

            options_bootstrapper = OptionsBootstrapper.create(args=sys.argv, env=os.environ)
            options, build_config = LocalPantsRunner.parse_options(options_bootstrapper)

            global_options = options.for_global_scope()
            session = self._scheduler_service.prepare_graph(options)

            specs = SpecsCalculator.create(
                options=options,
                session=session.scheduler_session,
                exclude_patterns=tuple(global_options.exclude_target_regexp),
                tags=tuple(global_options.tag) if global_options.tag else (),
            )

            if options.help_request:
                help_printer = HelpPrinter(
                    options=options, union_membership=UnionMembership(build_config.union_rules()),
                )
                return help_printer.print_help()

            exit_code = self._scheduler_service.graph_run_v2(
                session, specs, options, options_bootstrapper
            )
            # self.scheduler_service.graph_run_v2 will already run v2 or ambiguous goals. We should
            # only enter this code path if v1 is set.
            if global_options.v1:
                runner = LocalPantsRunner.create(self.env, options_bootstrapper, specs, session)

                env_start_time = self.env.pop("PANTSD_RUNTRACKER_CLIENT_START_TIME", None)
                start_time = float(env_start_time) if env_start_time else None
                runner.set_start_time(start_time)
                # TODO: This is almost certainly not correct: we should likely have the entire run
                # occur inside LocalPantsRunner now, and have it return an exit code directly.
                exit_code = runner.run()

            return exit_code

        except KeyboardInterrupt:
            print("Interrupted by user.\n", file=sys.stderr)
            return 1
        except Exception as e:
            ExceptionSink.log_unhandled_exception(exc=e)
            return 1

    def __call__(
        self,
        command: str,
        args: Tuple[str, ...],
        env: Dict[str, str],
        working_directory: bytes,
        stdin_fd: int,
        stdout_fd: int,
        stderr_fd: int,
    ) -> int:
        request_timeout = float(env.get("PANTSD_REQUEST_TIMEOUT_LIMIT", -1))
        # NB: Order matters: we acquire a lock before mutating either `sys.std*`, `os.environ`, etc.
        with self._one_run_at_a_time(stderr_fd, timeout=request_timeout), stdio_as(
            stdin_fd=stdin_fd, stdout_fd=stdout_fd, stderr_fd=stderr_fd
        ), hermetic_environment_as(**env), argv_as((command,) + args):
            # NB: Run implements exception handling, so only the most primitive errors will escape
            # this function, where they will be logged to the pantsd.log by the server.
            return self._run(working_directory.decode())
