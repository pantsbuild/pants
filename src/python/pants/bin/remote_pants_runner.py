# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import sys
import termios
import time
from contextlib import contextmanager
from typing import List, Mapping

from pants.base.exception_sink import ExceptionSink, SignalHandler
from pants.base.exiter import ExitCode
from pants.nailgun.nailgun_client import NailgunClient
from pants.nailgun.nailgun_protocol import NailgunProtocol
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_client import PantsDaemonClient
from pants.util.dirutil import maybe_read_file

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
    def __init__(self, pailgun_client: NailgunClient, pid: int, timeout: float = 1):
        self._pailgun_client = pailgun_client
        self._timeout = timeout
        self.pid = pid
        super().__init__(pantsd_instance=False)

    def _forward_signal_with_timeout(self, signum, signame):
        # TODO Consider not accessing the private function _maybe_last_pid here, or making it public.
        logger.info(
            "Sending {} to pantsd with pid {}, waiting up to {} seconds before sending SIGKILL...".format(
                signame, self.pid, self._timeout
            )
        )
        self._pailgun_client.set_exit_timeout(
            timeout=self._timeout,
            reason=KeyboardInterrupt("Sending user interrupt to pantsd"),
        )
        self._pailgun_client.maybe_send_signal(signum)

    def handle_sigint(self, signum, _frame):
        self._forward_signal_with_timeout(signum, "SIGINT")

    def handle_sigquit(self, signum, _frame):
        self._forward_signal_with_timeout(signum, "SIGQUIT")

    def handle_sigterm(self, signum, _frame):
        self._forward_signal_with_timeout(signum, "SIGTERM")


class RemotePantsRunner:
    """A thin client variant of PantsRunner."""

    class Fallback(Exception):
        """Raised when fallback to an alternate execution mode is requested."""

    class Terminated(Exception):
        """Raised when an active run is terminated mid-flight."""

    RECOVERABLE_EXCEPTIONS = (
        NailgunClient.NailgunConnectionError,
        NailgunClient.NailgunExecutionError,
    )

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

    @staticmethod
    def _backoff(attempt):
        """Minimal backoff strategy for daemon restarts."""
        time.sleep(attempt + (attempt - 1))

    def run(self) -> ExitCode:
        """Runs pants remotely with retry and recovery for nascent executions."""

        pantsd_handle = self._client.maybe_launch()
        retries = 3

        attempt = 1
        while True:
            logger.debug(
                "connecting to pantsd on port {} (attempt {}/{})".format(
                    pantsd_handle.port, attempt, retries
                )
            )
            try:
                return self._connect_and_execute(pantsd_handle)
            except self.RECOVERABLE_EXCEPTIONS as e:
                if attempt > retries:
                    raise self.Fallback(e)

                self._backoff(attempt)
                logger.warning(
                    "pantsd was unresponsive on port {}, retrying ({}/{})".format(
                        pantsd_handle.port, attempt, retries
                    )
                )

                # One possible cause of the daemon being non-responsive during an attempt might be if a
                # another lifecycle operation is happening concurrently (incl teardown). To account for
                # this, we won't begin attempting restarts until at least 1 second has passed (1 attempt).
                if attempt > 1:
                    pantsd_handle = self._client.restart()
                attempt += 1
            except NailgunClient.NailgunError as e:
                # Ensure a newline.
                logger.critical("")
                logger.critical("lost active connection to pantsd!")
                traceback = sys.exc_info()[2]
                raise self._extract_remote_exception(pantsd_handle.pid, e).with_traceback(traceback)

    def _connect_and_execute(self, pantsd_handle: PantsDaemonClient.Handle) -> ExitCode:
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

        # Instantiate a NailgunClient.
        client = NailgunClient(
            port=port,
            remote_pid=pid,
            ins=sys.stdin,
            out=sys.stdout.buffer,
            err=sys.stderr.buffer,
            exit_on_broken_pipe=True,
            metadata_base_dir=pantsd_handle.metadata_base_dir,
        )

        timeout = global_options.pantsd_pailgun_quit_timeout
        pantsd_signal_handler = PailgunClientSignalHandler(client, pid=pid, timeout=timeout)
        with ExceptionSink.trapped_signals(pantsd_signal_handler), STTYSettings.preserved():
            # Execute the command on the pailgun.
            return client.execute(self._args[0], self._args[1:], modified_env)

    def _extract_remote_exception(self, pantsd_pid, nailgun_error):
        """Given a NailgunError, returns a Terminated exception with additional info (where
        possible).

        This method will include the entire exception log for either the `pid` in the NailgunError,
        or failing that, the `pid` of the pantsd instance.
        """
        sources = [pantsd_pid]

        exception_text = None
        for source in sources:
            log_path = ExceptionSink.exceptions_log_path(for_pid=source)
            exception_text = maybe_read_file(log_path)
            if exception_text:
                break

        exception_suffix = (
            "\nRemote exception:\n{}".format(exception_text) if exception_text else ""
        )
        return self.Terminated(
            "abruptly lost active connection to pantsd runner: {!r}{}".format(
                nailgun_error, exception_suffix
            )
        )
