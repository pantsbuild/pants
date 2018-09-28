# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import signal
import sys
import time
from builtins import object, str
from contextlib import contextmanager

from pants.base.exception_sink import ExceptionSink, GetLogLocationRequest, LogLocation
from pants.base.exiter import Exiter
from pants.console.stty_utils import STTYSettings
from pants.java.nailgun_client import NailgunClient
from pants.java.nailgun_protocol import NailgunProtocol
from pants.pantsd.pants_daemon import PantsDaemon
from pants.util.collections import combined_dict
from pants.util.dirutil import maybe_read_file
from pants.util.osutil import safe_kill


logger = logging.getLogger(__name__)


class RemoteExiter(Exiter):
  """An Exiter that sends signals to and recovers logs from a remote process on failure."""

  def __init__(self, base_exiter):
    """Wrap an existing Exiter instance and initialize all of the remote process state to None."""
    assert(isinstance(base_exiter, Exiter))
    super(RemoteExiter, self).__init__()
    self._base_exiter = base_exiter
    # These fields are filled in at different stages of the remote client connection process, after
    # connecting to pantsd and then after the pantsd-runner daemonizes, so these are initialized
    # with register methods which are passed as callbacks to NailgunClient (and then to
    # NailgunClientSession). Each of these has a register method which ensures it is initialized <=
    # once.
    # This is the handle to the remote pantsd process.
    self._pantsd_handle = None
    # These are the pid and pgrp of the remote pantsd-runner process. The pid is used to collect
    # logs of any fatal errors from that remote process. The pgrp is used to broadcast any signals
    # sent to the entire process group of the remote pantsd-runner.
    self._client_pid = None
    self._client_pgrp = None

  # We provide a __str__ implementation to make it easier to produce error messages with all the
  # relevant state. The base_exiter is not expected to have a useful __str__ implementation.
  _STR_FMT = """\
RemoteExiter(base_exiter={base}, pantsd_handle={handle}, client_pid={pid}, client_pgrp={pgrp})"""

  def __str__(self):
    return self._STR_FMT.format(base=self._base_exiter,
                                handle=self._pantsd_handle,
                                pid=self._client_pid,
                                pgrp=self._client_pgrp)

  class RemotePantsRunnerExiterError(Exception): pass

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

  def _extract_remote_fatal_errors(self):
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

    for pid in source_pids:
      log_path = ExceptionSink.exceptions_log_path(GetLogLocationRequest(pid=pid))
      exception_text = maybe_read_file(log_path, binary_mode=False)
      if exception_text:
        yield exception_text

  def broadcast_signal_to_client(self, signum):
    try:
      # First try killing the process group id from the PGRP chunk of the nailgun connection.
      # TODO: is this the right signal to send?
      if self._client_pgrp:
        safe_kill(self._client_pgrp, signum)
      # Now try killing the client pid, in case the pgrp alone didn't work.
      # TODO: determine whether this is necessary if the pgrp kill was successful.
      if self._client_pid:
        safe_kill(self._client_pid, signum)
    except Exception as e:
      raise self.RemotePantsRunnerExiterError(
        'Error broadcasting signal {signum} to remote client with exiter {exiter}: {err}'
        .format(signum=signum,
                exiter=str(self),
                err=str(e)),
        e)

  def exit(self, result=0, msg=None, *args, **kwargs):
    accumulated_extra_error_messages = []

    # Ensure any connected pantsd-runner processes die when the remote client does.
    try:
      self.broadcast_signal_to_client(signal.SIGTERM)
    except Exception as e:
      accumulated_extra_error_messages.append(str(e))

    try:
      # Try to gather any exception logs for remote processes attached to this run.
      remote_fatal_errors = list(self._extract_remote_fatal_errors())
      if remote_fatal_errors:
        accumulated_extra_error_messages.append(
          'Remote exception:\n{}'.format('\n'.join(remote_fatal_errors)))
    except Exception as e:
      accumulated_extra_error_messages.append(
        'Error while shutting down the remote client: {}'.format(e))

    terminal_message = msg
    if accumulated_extra_error_messages:
      joined_error_messages = '\n\n'.join(accumulated_extra_error_messages)
      ExceptionSink.log_exception(joined_error_messages)
      logger.error(joined_error_messages)
      terminal_message = '{}\n{}'.format(joined_error_messages, (terminal_message or ''))

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
    # TODO: this ^C fix should probably be done in the ExceptionSink, or at least the process-global
    # signal handler registration should all be done in one place.
    def handle_control_c(signum, frame):
      err_msg = None
      try:
        # TODO: this could probably wait on the remote process to die (somehow) after sending the
        # remote control-c, to avoid command-line control-c misbehavior!
        self._exiter.broadcast_signal_to_client(signal.SIGINT)
      except Exception as e:
        err_msg = ('Error sending control-c to remote client with exiter {}: {}'
                   .format(self._exiter, e))
        ExceptionSink.log_exception(err_msg)
        logger.error(err_msg)

        # Delegate to the ExceptionSink signal handler after sending SIGINT.
        # TODO: this functionality should probably be moved to Exiter.
        ExceptionSink.handle_signal_gracefully(signum, frame)

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

        raise self.Terminated('abruptly lost active connection to pantsd runner: {!r}'.format(e),
                              e)

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
      # The pid and pgrp fields are populated when the nailgun connection receives PID and PGRP
      # chunks. This can occur at any time, or not at all, and we drop these values when the session
      # completes, so we use callbacks to avoid having to check for None or keep them around longer
      # than we need to.
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
