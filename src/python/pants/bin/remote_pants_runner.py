# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import sys
import termios
import time
from contextlib import contextmanager
from typing import List, Mapping

import psutil

from pants.base.exception_sink import ExceptionSink, SignalHandler
from pants.base.exiter import ExitCode
from pants.engine.internals.native import Native
from pants.nailgun.nailgun_protocol import NailgunProtocol
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_client import PantsDaemonClient

logger = logging.getLogger(__name__)


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


class PailgunClientSignalHandler(SignalHandler):
    def __init__(self, pid: int):
        self.pid = pid
        super().__init__(pantsd_instance=False)

    def _forward_signal(self, signum, signame):
        ExceptionSink._signal_sent = signum
        logger.info(f"Sending {signame} to pantsd with pid {self.pid}")
        pantsd_process = psutil.Process(pid=self.pid)
        pantsd_process.send_signal(signum)

    def handle_sigint(self, signum, _frame):
        self._forward_signal(signum, "SIGINT")

    def handle_sigquit(self, signum, _frame):
        self._forward_signal(signum, "SIGQUIT")

    def handle_sigterm(self, signum, _frame):
        self._forward_signal(signum, "SIGTERM")


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
        native = Native()

        port = pantsd_handle.port
        pid = pantsd_handle.pid
        global_options = self._bootstrap_options.for_global_scope()

        # Merge the nailgun TTY capability environment variables with the passed environment dict.
        ng_env = NailgunProtocol.ttynames_to_env(sys.stdin, sys.stdout.buffer, sys.stderr.buffer)
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

        def signal_fn() -> bool:
            return ExceptionSink.signal_sent() is not None

        rust_nailgun_client = native.new_nailgun_client(port=port)
        pantsd_signal_handler = PailgunClientSignalHandler(pid=pid)

        retries = 3
        attempt = 1
        while True:
            logger.debug(f"Connecting to pantsd on port {port} attempt {attempt}/{retries}")

            with ExceptionSink.trapped_signals(pantsd_signal_handler), STTYSettings.preserved():
                try:
                    output = rust_nailgun_client.execute(signal_fn, command, args, modified_env)
                    return output

                # NailgunConnectionException represents a failure connecting to pantsd, so we retry
                # up to the retry limit.
                except native.lib.NailgunConnectionException as e:
                    if attempt > retries:
                        raise self.Fallback(e)

                    # Wait one second before retrying
                    logger.warning(f"Pantsd was unresponsive on port {port}, retrying.")
                    time.sleep(1)
                    attempt += 1
