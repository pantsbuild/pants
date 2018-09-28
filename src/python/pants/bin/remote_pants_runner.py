# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import signal
import sys
import time
from builtins import object, str
from contextlib import contextmanager

from future.utils import raise_with_traceback

from pants.base.exception_sink import ExceptionSink, GetLogLocationRequest, LogLocation
from pants.base.exiter import Exiter
from pants.console.stty_utils import STTYSettings
from pants.java.nailgun_client import NailgunClient
from pants.java.nailgun_protocol import NailgunProtocol
from pants.pantsd.pants_daemon import PantsDaemon
from pants.util.collections import combined_dict
from pants.util.dirutil import maybe_read_file


logger = logging.getLogger(__name__)


class RemoteExiter(Exiter):

  def __init__(self, base_exiter):
    assert(isinstance(base_exiter, Exiter))
    super(RemoteExiter, self).__init__()
    self._base_exiter = base_exiter
    self._pantsd_handle = None
    self._client_pid = None
    self._client_pgrp = None

  # TODO: figure out whether it's useful to log whether these mutators were or weren't called.
  def register_pantsd_handle(self, pantsd_handle):
    assert(self._pantsd_handle is None)
    assert(isinstance(pantsd_handle, PantsDaemon.Handle))
    self._pantsd_handle = pantsd_handle

  def register_client_pid(self, client_pid):
    assert(self._client_pid is None)
    assert(isinstance(client_pid, (int, long)) and client_pid > 0)
    self._client_pid = client_pid

  def register_client_pgrp(self, client_pgrp):
    assert(self._client_pgrp is None)
    assert(isinstance(client_pgrp, (int, long)) and client_pgrp < 0)
    self._client_pgrp = client_pgrp

  def _extract_remote_exception(self):
    """Given a NailgunError, returns a Terminated exception with additional info (where possible).

    This method will include the entire exception log for either the `pid` in the NailgunError, or
    failing that, the `pid` of the pantsd instance.
    """
    source_pids = []

    assert(self._pantsd_handle is not None)
    source_pids.append(self._pantsd_handle.pid)

    # This may not have been registered yet, so None.
    if self._client_pid:
      source_pids.append(self._client_pid)

    exception_text = None
    for pid in source_pids:
      log_path = ExceptionSink.exceptions_log_path(GetLogLocationRequest(pid=pid))
      exception_text = maybe_read_file(log_path, binary_mode=False)
      if exception_text:
        break

    return exception_text

  def exit(self, result=0, msg=None, *args, **kwargs):
    # NB: We use (terminal_message or '') in this method instead of mutating `msg` in order to
    # preserve an `msg=None` argument value.
    terminal_message = msg

    # Ensure any connected pantsd-runner processes die when the remote client does.
    try:
      # TODO: is this the right signal to send?
      # TODO: self._client_pgrp should have been filled by now!
      if self._client_pgrp:
        os.kill(self._client_pgrp, signal.SIGTERM)
    except Exception as e:
      terminal_message = ('{}\nAdditional error killing nailgun client upon exit: {}'
                          .format((terminal_message or ''), e))

    # Ensure the remote exception is at the bottom of the output.
    try:
      remote_error_message = self._extract_remote_exception()
      if remote_error_message:
        ExceptionSink.log_exception(remote_error_message)
        terminal_message = ('{}\nRemote exception:\n{}'
                            .format((terminal_message or ''), remote_error_message))
    except Exception as e:
      terminal_message = ('{}\nAdditional error finding remote client error logs: {}'
                          .format((terminal_message or ''), e))

    self._base_exiter.exit(result=result, msg=terminal_message, *args, **kwargs)


class RemotePantsRunner(object):
  """A thin client variant of PantsRunner."""

  class Fallback(Exception):
    """Raised when fallback to an alternate execution mode is requested."""

  class Terminated(Exception):
    """Raised when an active run is terminated mid-flight."""

  PANTS_COMMAND = 'pants'
  RECOVERABLE_EXCEPTIONS = (
    NailgunClient.NailgunConnectionError,
    NailgunClient.NailgunExecutionError
  )

  def __init__(self, exiter, args, env, bootstrap_options, stdin=None, stdout=None, stderr=None):
    """
    :param Exiter exiter: The Exiter instance to use for this run.
    :param list args: The arguments (e.g. sys.argv) for this run.
    :param dict env: The environment (e.g. os.environ) for this run.
    :param Options bootstrap_options: The Options bag containing the bootstrap options.
    :param file stdin: The stream representing stdin.
    :param file stdout: The stream representing stdout.
    :param file stderr: The stream representing stderr.
    """
    self._start_time = time.time()
    self._exiter = exiter
    self._args = args
    self._env = env
    self._bootstrap_options = bootstrap_options
    self._stdin = stdin or sys.stdin
    self._stdout = stdout or sys.stdout
    self._stderr = stderr or sys.stderr

  @contextmanager
  def _trapped_signals(self, client):
    """A contextmanager that overrides the SIGINT (control-c) and SIGQUIT (control-\) handlers
    and handles them remotely."""
    # TODO: if this control-c is done at the wrong time (before the pantsd-runner process begins and
    # sets the pid in the client), the pantsd-runner process will just send input to the terminal
    # without respecting control-c or anything else until it exits.
    def handle_control_c(signum, frame):
      try:
        client.send_control_c()
      except Exception as e:
        msg = 'Error sending control-c to remote client: {}'.format(e)
        logger.error(msg)
        ExceptionSink.log_exception(msg)
      finally:
        # TODO: this should exit immediately here or wait on the remote process to die after sending
        # the remote control-c to avoid command-line control-c misbehavior!
        # TODO: don't do this yet!
        ExceptionSink._handle_signal_gracefully(signum, frame)

    existing_sigint_handler = signal.signal(signal.SIGINT, handle_control_c)
    # N.B. SIGQUIT will abruptly kill the pantsd-runner, which will shut down the other end
    # of the Pailgun connection - so we send a gentler SIGINT here instead.
    existing_sigquit_handler = signal.signal(signal.SIGQUIT, handle_control_c)

    # Retry interrupted system calls.
    signal.siginterrupt(signal.SIGINT, False)
    signal.siginterrupt(signal.SIGQUIT, False)
    try:
      yield
    finally:
      signal.signal(signal.SIGINT, existing_sigint_handler)
      signal.signal(signal.SIGQUIT, existing_sigquit_handler)

  def _setup_stderr_logging(self):
    """Sets up basic stdio logging for the thin client."""
    log_level = logging.getLevelName(self._bootstrap_options.for_global_scope().level.upper())

    err_stream = sys.stderr

    formatter = logging.Formatter('%(levelname)s] %(message)s')
    handler = logging.StreamHandler(err_stream)
    handler.setLevel(log_level)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.addHandler(handler)

    return err_stream

  @staticmethod
  def _backoff(attempt):
    """Minimal backoff strategy for daemon restarts."""
    time.sleep(attempt + (attempt - 1))

  def _run_pants_with_retry(self, pantsd_handle, retries=3):
    """Runs pants remotely with retry and recovery for nascent executions.

    :param PantsDaemon.Handle pantsd_handle: A Handle for the daemon to connect to.
    """
    attempt = 1
    while 1:
      logger.debug(
        'connecting to pantsd on port {} (attempt {}/{})'
        .format(pantsd_handle.port, attempt, retries)
      )
      try:
        return self._connect_and_execute(pantsd_handle.port)
      except self.RECOVERABLE_EXCEPTIONS as e:
        if attempt > retries:
          raise self.Fallback(e)

        self._backoff(attempt)
        logger.warn(
          'pantsd was unresponsive on port {}, retrying ({}/{})'
          .format(pantsd_handle.port, attempt, retries)
        )

        # One possible cause of the daemon being non-responsive during an attempt might be if a
        # another lifecycle operation is happening concurrently (incl teardown). To account for
        # this, we won't begin attempting restarts until at least 1 second has passed (1 attempt).
        if attempt > 1:
          pantsd_handle = self._restart_pantsd()
        attempt += 1
      except NailgunClient.NailgunError as e:
        # Ensure a newline.
        error_log_msg = '\nlost active connection to pantsd!'
        ExceptionSink.log_exception(error_log_msg)
        logger.fatal(error_log_msg)

        wrapped_exc = self.Terminated('abruptly lost active connection to pantsd runner: {!r}'
                                      .format(e),
                                      e)
        # TODO: figure out if we can remove raise_with_traceback() here.
        raise_with_traceback(wrapped_exc)

  def _connect_and_execute(self, port):
    # Merge the nailgun TTY capability environment variables with the passed environment dict.
    ng_env = NailgunProtocol.isatty_to_env(self._stdin, self._stdout, self._stderr)
    modified_env = combined_dict(self._env, ng_env)
    modified_env['PANTSD_RUNTRACKER_CLIENT_START_TIME'] = str(self._start_time)

    assert isinstance(port, int), 'port {} is not an integer!'.format(port)

    # Instantiate a NailgunClient.
    client = NailgunClient(
      port=port,
      ins=self._stdin,
      out=self._stdout,
      err=self._stderr,
      exit_on_broken_pipe=True,
      expects_pid=True,
      # TODO: ???
      remote_pid_callback=(lambda pid: self._exiter.register_client_pid(pid)),
      remote_pgrp_callback=(lambda pgrp: self._exiter.register_client_pgrp(pgrp)))

    with self._trapped_signals(client), STTYSettings.preserved():
      # Execute the command on the pailgun.
      result = client.execute(self.PANTS_COMMAND, *self._args, **modified_env)

    # Exit.
    self._exiter.exit(result)

  def _restart_pantsd(self):
    return PantsDaemon.Factory.restart(bootstrap_options=self._bootstrap_options)

  def _maybe_launch_pantsd(self):
    return PantsDaemon.Factory.maybe_launch(bootstrap_options=self._bootstrap_options)

  def run(self, args=None):
    # Redirect fatal error logging to the current workdir, set the stream to log stacktraces to on
    # SIGUSR2, and recognize the provided Exiter.
    ExceptionSink.reset_log_location(LogLocation.from_options_for_current_process(
      self._bootstrap_options.for_global_scope()))
    ExceptionSink.reset_interactive_output_stream(self._setup_stderr_logging())
    # Mutate the exiter to be able to track pids.
    self._exiter = RemoteExiter(self._exiter)
    ExceptionSink.reset_exiter(self._exiter)

    pantsd_handle = self._maybe_launch_pantsd()
    # Add the logs for this pantsd process to our logs when exiting.
    self._exiter.register_pantsd_handle(pantsd_handle)
    self._run_pants_with_retry(pantsd_handle)
