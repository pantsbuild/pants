# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import sys
import time
from contextlib import contextmanager
from typing import List, Mapping

from pants.base.exception_sink import ExceptionSink, SignalHandler
from pants.console.stty_utils import STTYSettings
from pants.java.nailgun_client import NailgunClient
from pants.java.nailgun_protocol import NailgunProtocol
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon import PantsDaemon
from pants.util.dirutil import maybe_read_file

logger = logging.getLogger(__name__)


class PailgunClientSignalHandler(SignalHandler):
    def __init__(self, pailgun_client, pid, timeout=1, *args, **kwargs):
        assert isinstance(pailgun_client, NailgunClient)
        self._pailgun_client = pailgun_client
        self._timeout = timeout
        self.pid = pid
        super().__init__(*args, **kwargs)

    def _forward_signal_with_timeout(self, signum, signame):
        # TODO Consider not accessing the private function _maybe_last_pid here, or making it public.
        logger.info(
            "Sending {} to pantsd with pid {}, waiting up to {} seconds before sending SIGKILL...".format(
                signame, self.pid, self._timeout
            )
        )
        self._pailgun_client.set_exit_timeout(
            timeout=self._timeout,
            reason=KeyboardInterrupt("Interrupted by user over pailgun client!"),
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

    PANTS_COMMAND = "pants"
    RECOVERABLE_EXCEPTIONS = (
        NailgunClient.NailgunConnectionError,
        NailgunClient.NailgunExecutionError,
    )

    def __init__(
        self,
        exiter,
        args: List[str],
        env: Mapping[str, str],
        options_bootstrapper: OptionsBootstrapper,
        stdin=None,
        stdout=None,
        stderr=None,
    ) -> None:
        """
        :param Exiter exiter: The Exiter instance to use for this run.
        :param args: The arguments (e.g. sys.argv) for this run.
        :param env: The environment (e.g. os.environ) for this run.
        :param options_bootstrapper: The bootstrap options.
        :param file stdin: The stream representing stdin.
        :param file stdout: The stream representing stdout.
        :param file stderr: The stream representing stderr.
        """
        self._start_time = time.time()
        self._exiter = exiter
        self._args = args
        self._env = env
        self._options_bootstrapper = options_bootstrapper
        self._bootstrap_options = options_bootstrapper.bootstrap_options
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout.buffer
        self._stderr = stderr or sys.stderr.buffer

    @contextmanager
    def _trapped_signals(self, client, pid: int):
        """A contextmanager that handles SIGINT (control-c) and SIGQUIT (control-\\) remotely."""
        signal_handler = PailgunClientSignalHandler(
            client,
            pid=pid,
            timeout=self._bootstrap_options.for_global_scope().pantsd_pailgun_quit_timeout,
        )
        with ExceptionSink.trapped_signals(signal_handler):
            yield

    @staticmethod
    def _backoff(attempt):
        """Minimal backoff strategy for daemon restarts."""
        time.sleep(attempt + (attempt - 1))

    def _run_pants_with_retry(self, pantsd_handle: PantsDaemon.Handle, retries: int = 3):
        """Runs pants remotely with retry and recovery for nascent executions.

        :param pantsd_handle: A Handle for the daemon to connect to.
        """
        attempt = 1
        while 1:
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
                    pantsd_handle = self._restart_pantsd()
                attempt += 1
            except NailgunClient.NailgunError as e:
                # Ensure a newline.
                logger.critical("")
                logger.critical("lost active connection to pantsd!")
                traceback = sys.exc_info()[2]
                raise self._extract_remote_exception(pantsd_handle.pid, e).with_traceback(traceback)

    def _connect_and_execute(self, pantsd_handle: PantsDaemon.Handle):
        port = pantsd_handle.port
        pid = pantsd_handle.pid
        # Merge the nailgun TTY capability environment variables with the passed environment dict.
        ng_env = NailgunProtocol.isatty_to_env(self._stdin, self._stdout, self._stderr)
        modified_env = {
            **self._env,
            **ng_env,
            "PANTSD_RUNTRACKER_CLIENT_START_TIME": str(self._start_time),
            "PANTSD_REQUEST_TIMEOUT_LIMIT": str(
                self._bootstrap_options.for_global_scope().pantsd_timeout_when_multiple_invocations
            ),
        }

        assert isinstance(port, int), "port {} is not an integer! It has type {}.".format(
            port, type(port)
        )

        # Instantiate a NailgunClient.
        client = NailgunClient(
            port=port,
            remote_pid=pid,
            ins=self._stdin,
            out=self._stdout,
            err=self._stderr,
            exit_on_broken_pipe=True,
            metadata_base_dir=pantsd_handle.metadata_base_dir,
        )

        with self._trapped_signals(client, pantsd_handle.pid), STTYSettings.preserved():
            # Execute the command on the pailgun.
            result = client.execute(self.PANTS_COMMAND, *self._args, **modified_env)

        # Exit.
        self._exiter.exit(result)

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

    def _restart_pantsd(self):
        return PantsDaemon.Factory.restart(options_bootstrapper=self._options_bootstrapper)

    def run(self, args=None) -> None:
        handle = PantsDaemon.Factory.maybe_launch(options_bootstrapper=self._options_bootstrapper)
        self._run_pants_with_retry(handle)
