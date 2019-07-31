# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
import termios
import time
from contextlib import contextmanager
from typing import Callable

from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, ExitCode, Exiter
from pants.bin.local_pants_runner import LocalPantsRunner
from pants.init.logging import encapsulated_global_logger
from pants.init.util import clean_global_runtime_state
from pants.java.nailgun_io import (NailgunStreamStdinReader, NailgunStreamWriterError,
                                   PipedNailgunStreamWriter)
from pants.java.nailgun_protocol import ChunkType, MaybeShutdownSocket, NailgunProtocol
from pants.util.contextutil import hermetic_environment_as, stdio_as
from pants.util.socket import teardown_socket


class PantsRunFailCheckerExiter(Exiter):
  """Passed to pants runs triggered from this class, will raise an exception if the pants run failed."""

  def exit(self, result, *args, **kwargs):
    if result != 0:
      raise _PantsRunFinishedWithFailureException(result)


class DaemonExiter(Exiter):
  """An Exiter that emits unhandled tracebacks and exit codes via the Nailgun protocol."""

  @classmethod
  @contextmanager
  def override_global_exiter(cls, maybe_shutdown_socket: MaybeShutdownSocket, finalizer: Callable[[], None]) -> None:
    with ExceptionSink.exiter_as(lambda previous_exiter: cls(maybe_shutdown_socket, finalizer, previous_exiter)):
      yield

  def __init__(self,
    maybe_shutdown_socket: MaybeShutdownSocket,
    finalizer: Callable[[], None],
    previous_exiter: Exiter):

    super().__init__(exiter=previous_exiter)
    self._maybe_shutdown_socket = maybe_shutdown_socket
    self._finalizer = finalizer

  def exit(self, result: ExitCode = 0, msg: str = None, *args, **kwargs):
    """Exit the runtime."""
    if self._finalizer:
      try:
        self._finalizer()
      except Exception as e:
        try:
          with self._maybe_shutdown_socket.lock:
            NailgunProtocol.send_stderr(
              self._maybe_shutdown_socket.socket,
              '\nUnexpected exception in finalizer: {!r}\n'.format(e)
            )
        except Exception:
          pass

    with self._maybe_shutdown_socket.lock:
      # Write a final message to stderr if present.
      if msg:
        NailgunProtocol.send_stderr(self._maybe_shutdown_socket.socket, msg)

      # Send an Exit chunk with the result.
      # This will cause the client to disconnect from the socket.
      NailgunProtocol.send_exit_with_code(self._maybe_shutdown_socket.socket, result)

      # Shutdown the connected socket.
      teardown_socket(self._maybe_shutdown_socket.socket)
      self._maybe_shutdown_socket.is_shutdown = True


class _PantsRunFinishedWithFailureException(Exception):
  """
  Allows representing a pants run that failed for legitimate reasons
  (e.g. the target failed to compile).

  Will be raised by the exiter passed to LocalPantsRunner.
  """

  def __init__(self, exit_code: ExitCode = PANTS_FAILED_EXIT_CODE):
    """
    :param int exit_code: an optional exit code (defaults to PANTS_FAILED_EXIT_CODE)
    """
    super(_PantsRunFinishedWithFailureException, self).__init__('Terminated with {}'.format(exit_code))

    if exit_code == PANTS_SUCCEEDED_EXIT_CODE:
      raise ValueError(
        "Cannot create {} with a successful exit code of {}"
        .format(type(self).__name__, PANTS_SUCCEEDED_EXIT_CODE))

    self._exit_code = exit_code

  @property
  def exit_code(self) -> ExitCode:
    return self._exit_code


class DaemonPantsRunner(ExceptionSink.AccessGlobalExiterMixin):
  """A daemonizing PantsRunner that speaks the nailgun protocol to a remote client.

  N.B. this class is primarily used by the PailgunService in pantsd.
  """

  @classmethod
  def create(cls, sock, args, env, services, scheduler_service):
    return cls(
      maybe_shutdown_socket=MaybeShutdownSocket(sock),
      args=args,
      env=env,
      services=services,
      scheduler_service=scheduler_service
    )

  def __init__(self, maybe_shutdown_socket, args, env, services, scheduler_service):
    """
    :param MaybeShutdownSocket maybe_shutdown_socket: A connected socket capable of speaking the nailgun protocol.
    :param list args: The arguments (i.e. sys.argv) for this run.
    :param dict env: The environment (i.e. os.environ) for this run.
    :param PantsServices services: The PantsServices that are currently running.
    :param SchedulerService scheduler_service: The SchedulerService that holds the warm graph.
    """
    self._maybe_shutdown_socket = maybe_shutdown_socket
    self._args = args
    self._env = env
    self._services = services
    self._scheduler_service = scheduler_service

    self.exit_code = PANTS_SUCCEEDED_EXIT_CODE

  @classmethod
  @contextmanager
  def _tty_stdio(cls, env):
    """Handles stdio redirection in the case of all stdio descriptors being the same tty."""
    # If all stdio is a tty, there's only one logical I/O device (the tty device). This happens to
    # be addressable as a file in OSX and Linux, so we take advantage of that and directly open the
    # character device for output redirection - eliminating the need to directly marshall any
    # interactive stdio back/forth across the socket and permitting full, correct tty control with
    # no middle-man.
    stdin_ttyname, stdout_ttyname, stderr_ttyname = NailgunProtocol.ttynames_from_env(env)
    assert stdin_ttyname == stdout_ttyname == stderr_ttyname, (
      'expected all stdio ttys to be the same, but instead got: {}\n'
      'please file a bug at http://github.com/pantsbuild/pants'
      .format([stdin_ttyname, stdout_ttyname, stderr_ttyname])
    )
    with open(stdin_ttyname, 'rb+', 0) as tty:
      tty_fileno = tty.fileno()
      with stdio_as(stdin_fd=tty_fileno, stdout_fd=tty_fileno, stderr_fd=tty_fileno):
        def finalizer():
          termios.tcdrain(tty_fileno)
        yield finalizer

  @classmethod
  @contextmanager
  def _pipe_stdio(cls, maybe_shutdown_socket, stdin_isatty, stdout_isatty, stderr_isatty, handle_stdin):
    """Handles stdio redirection in the case of pipes and/or mixed pipes and ttys."""
    stdio_writers = (
      (ChunkType.STDOUT, stdout_isatty),
      (ChunkType.STDERR, stderr_isatty)
    )
    types, ttys = zip(*(stdio_writers))

    @contextmanager
    def maybe_handle_stdin(want):
      if want:
        with NailgunStreamStdinReader.open(maybe_shutdown_socket, stdin_isatty) as fd:
          yield fd
      else:
        with open('/dev/null', 'rb') as fh:
          yield fh.fileno()

    # TODO https://github.com/pantsbuild/pants/issues/7653
    with maybe_handle_stdin(handle_stdin) as stdin_fd,\
      PipedNailgunStreamWriter.open_multi(maybe_shutdown_socket.socket, types, ttys) as ((stdout_pipe, stderr_pipe), writer),\
      stdio_as(stdout_fd=stdout_pipe.write_fd, stderr_fd=stderr_pipe.write_fd, stdin_fd=stdin_fd):
      # N.B. This will be passed to and called by the `DaemonExiter` prior to sending an
      # exit chunk, to avoid any socket shutdown vs write races.
      stdout, stderr = sys.stdout, sys.stderr
      def finalizer():
        try:
          stdout.flush()
          stderr.flush()
        finally:
          time.sleep(.001)  # HACK: Sleep 1ms in the main thread to free the GIL.
          stdout_pipe.stop_writing()
          stderr_pipe.stop_writing()
          writer.join(timeout=60)
          if writer.isAlive():
            raise NailgunStreamWriterError("pantsd timed out while waiting for the stdout/err to finish writing to the socket.")
      yield finalizer

  @classmethod
  @contextmanager
  def nailgunned_stdio(cls, sock, env, handle_stdin=True):
    """Redirects stdio to the connected socket speaking the nailgun protocol."""
    # Determine output tty capabilities from the environment.
    stdin_isatty, stdout_isatty, stderr_isatty = NailgunProtocol.isatty_from_env(env)
    is_tty_capable = all((stdin_isatty, stdout_isatty, stderr_isatty))

    if is_tty_capable:
      with cls._tty_stdio(env) as finalizer:
        yield finalizer
    else:
      with cls._pipe_stdio(
        sock,
        stdin_isatty,
        stdout_isatty,
        stderr_isatty,
        handle_stdin
      ) as finalizer:
        yield finalizer

  def _maybe_get_client_start_time_from_env(self, env):
    client_start_time = env.pop('PANTSD_RUNTRACKER_CLIENT_START_TIME', None)
    return None if client_start_time is None else float(client_start_time)

  def run(self):
    # Ensure anything referencing sys.argv inherits the Pailgun'd args.
    sys.argv = self._args

    # Broadcast our process group ID (in PID form - i.e. negated) to the remote client so
    # they can send signals (e.g. SIGINT) to all processes in the runners process group.
    with self._maybe_shutdown_socket.lock:
      NailgunProtocol.send_pid(self._maybe_shutdown_socket.socket, os.getpid())
      NailgunProtocol.send_pgrp(self._maybe_shutdown_socket.socket, os.getpgrp() * -1)

    # Invoke a Pants run with stdio redirected and a proxied environment.
    with self.nailgunned_stdio(self._maybe_shutdown_socket, self._env) as finalizer, \
      DaemonExiter.override_global_exiter(self._maybe_shutdown_socket, finalizer), \
      hermetic_environment_as(**self._env), \
      encapsulated_global_logger():
      try:
        # Clean global state.
        clean_global_runtime_state(reset_subsystem=True)

        options, _, options_bootstrapper = LocalPantsRunner.parse_options(self._args, self._env)
        graph_helper, target_roots, exit_code = self._scheduler_service.prepare_v1_graph_run_v2(options, options_bootstrapper)
        self.exit_code = exit_code

        # Otherwise, conduct a normal run.
        with ExceptionSink.exiter_as_until_exception(lambda _: PantsRunFailCheckerExiter()):
          runner = LocalPantsRunner.create(
            self._args,
            self._env,
            target_roots,
            graph_helper,
            options_bootstrapper,
          )
          runner.set_start_time(self._maybe_get_client_start_time_from_env(self._env))

          runner.run()
      except KeyboardInterrupt:
        self._exiter.exit_and_fail('Interrupted by user.\n')
      except _PantsRunFinishedWithFailureException as e:
        ExceptionSink.log_exception(
          'Pants run failed with exception: {}; exiting'.format(e))
        self._exiter.exit(e.exit_code)
      except Exception as e:
        # TODO: We override sys.excepthook above when we call ExceptionSink.set_exiter(). That
        # excepthook catches `SignalHandledNonLocalExit`s from signal handlers, which isn't
        # happening here, so something is probably overriding the excepthook. By catching Exception
        # and calling this method, we emulate the normal, expected sys.excepthook override.
        ExceptionSink._log_unhandled_exception_and_exit(exc=e)
      else:
        self._exiter.exit(self.exit_code if self.exit_code else PANTS_SUCCEEDED_EXIT_CODE)
