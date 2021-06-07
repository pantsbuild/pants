# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import signal
import sys
import termios
import time
from contextlib import contextmanager
from typing import List, Mapping

from pants.base.exiter import ExitCode
from pants.engine.internals import native_engine
from pants.engine.internals.native_engine import PantsdConnectionException
from pants.nailgun.nailgun_protocol import NailgunProtocol
from pants.option.global_options import GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_client import PantsDaemonClient

logger = logging.getLogger(__name__)


@contextmanager
def interrupts_ignored():
    """Disables Python's default interrupt handling."""
    old_handler = signal.signal(signal.SIGINT, handler=lambda s, f: None)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old_handler)


class STTYSettings:
    """Saves/restores stty settings."""

    @classmethod
    @contextmanager
    def preserved(cls):
        """Run potentially stty-modifying operations, e.g., REPL execution, in this
        contextmanager."""
        inst = cls()
        inst.save_tty_flags()
        try:
            yield
        finally:
            inst.restore_tty_flags()

    def __init__(self):
        self._tty_flags = None

    def save_tty_flags(self):
        # N.B. `stty(1)` operates against stdin.
        try:
            self._tty_flags = termios.tcgetattr(sys.stdin.fileno())
        except termios.error as e:
            logger.debug("masking tcgetattr exception: {!r}".format(e))

    def restore_tty_flags(self):
        if self._tty_flags:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, self._tty_flags)
            except termios.error as e:
                logger.debug("masking tcsetattr exception: {!r}".format(e))


class RemotePantsRunner:
    """A thin client variant of PantsRunner."""

    class Fallback(Exception):
        """Raised when fallback to an alternate execution mode is requested."""

    class Terminated(Exception):
        """Raised when an active run is terminated mid-flight."""

    def __init__(
        self,
        args: List[str],
        env: Mapping[str, str],
        options_bootstrapper: OptionsBootstrapper,
    ) -> None:
        """
        :param args: The arguments (e.g. sys.argv) for this run.
        :param env: The environment (e.g. os.environ) for this run.
        :param options_bootstrapper: The bootstrap options.
        """
        self._start_time = time.time()
        self._args = args
        self._env = env
        self._options_bootstrapper = options_bootstrapper
        self._bootstrap_options = options_bootstrapper.bootstrap_options
        self._client = PantsDaemonClient(self._bootstrap_options)

    def run(self) -> ExitCode:
        """Starts up a pantsd instance if one is not already running, then connects to it via
        nailgun."""

        pantsd_handle = self._client.maybe_launch()
        logger.debug(f"Connecting to pantsd on port {pantsd_handle.port}")

        return self._connect_and_execute(pantsd_handle)

    def _connect_and_execute(self, pantsd_handle: PantsDaemonClient.Handle) -> ExitCode:
        global_options = self._bootstrap_options.for_global_scope()
        executor = GlobalOptions.create_py_executor(global_options)

        # Merge the nailgun TTY capability environment variables with the passed environment dict.
        ng_env = NailgunProtocol.ttynames_to_env(sys.stdin, sys.stdout, sys.stderr)
        modified_env = {
            **self._env,
            **ng_env,
            "PANTSD_RUNTRACKER_CLIENT_START_TIME": str(self._start_time),
            "PANTSD_REQUEST_TIMEOUT_LIMIT": str(
                global_options.pantsd_timeout_when_multiple_invocations
            ),
        }

        command = self._args[0]
        args = self._args[1:]

        retries = 3
        attempt = 1
        while True:
            port = pantsd_handle.port
            logger.debug(f"Connecting to pantsd on port {port} attempt {attempt}/{retries}")

            # We preserve TTY settings since the server might write directly to the TTY, and we'd like
            # to clean up any side effects before exiting.
            #
            # We ignore keyboard interrupts because the nailgun client will handle them.
            with STTYSettings.preserved(), interrupts_ignored():
                try:
                    return native_engine.nailgun_client_create(executor, port).execute(
                        command, args, modified_env
                    )
                # Retry if we failed to connect to Pantsd.
                except PantsdConnectionException as e:
                    if attempt > retries:
                        raise self.Fallback(e)

                    # Wait one second before retrying
                    logger.warning(f"Pantsd was unresponsive on port {port}, retrying.")
                    time.sleep(1)

                    # One possible cause of the daemon being non-responsive during an attempt might be if a
                    # another lifecycle operation is happening concurrently (incl teardown). To account for
                    # this, we won't begin attempting restarts until at least 1 attempt has passed.
                    if attempt > 1:
                        pantsd_handle = self._client.restart()

                    attempt += 1
