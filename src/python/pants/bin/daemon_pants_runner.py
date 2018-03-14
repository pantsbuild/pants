# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import datetime
import os
import signal
import sys
import termios
import time
from contextlib import contextmanager

from setproctitle import setproctitle as set_process_title

from pants.base.exiter import Exiter
from pants.bin.local_pants_runner import LocalPantsRunner
from pants.init.util import clean_global_runtime_state
from pants.java.nailgun_io import NailgunStreamStdinReader, NailgunStreamWriter
from pants.java.nailgun_protocol import ChunkType, NailgunProtocol
from pants.pantsd.process_manager import ProcessManager
from pants.util.contextutil import HardSystemExit, hermetic_environment_as, stdio_as
from pants.util.socket import teardown_socket


class DaemonExiter(Exiter):
  """An Exiter that emits unhandled tracebacks and exit codes via the Nailgun protocol."""

  def __init__(self, socket):
    super(DaemonExiter, self).__init__()
    self._socket = socket
    self._finalizer = None

  def set_finalizer(self, finalizer):
    """Sets a finalizer that will be called before exiting."""
    self._finalizer = finalizer

  def exit(self, result=0, msg=None):
    """Exit the runtime."""
    if self._finalizer:
      try:
        self._finalizer()
      except Exception as e:
        try:
          NailgunProtocol.send_stderr(
            self._socket,
            '\nUnexpected exception in finalizer: {!r}\n'.format(e)
          )
        except Exception:
          pass

    try:
      # Write a final message to stderr if present.
      if msg:
        NailgunProtocol.send_stderr(self._socket, msg)

      # Send an Exit chunk with the result.
      NailgunProtocol.send_exit(self._socket, str(result).encode('ascii'))

      # Shutdown the connected socket.
      teardown_socket(self._socket)
    finally:
      # N.B. Assuming a fork()'d child, cause os._exit to be called here to avoid the routine
      # sys.exit behavior (via `pants.util.contextutil.hard_exit_handler()`).
      raise HardSystemExit()


class DaemonPantsRunner(ProcessManager):
  """A daemonizing PantsRunner that speaks the nailgun protocol to a remote client.

  N.B. this class is primarily used by the PailgunService in pantsd.
  """

  def __init__(self, socket, exiter, args, env, target_roots, graph_helper, fork_lock,
               preceding_graph_size, deferred_exception=None):
    """
    :param socket socket: A connected socket capable of speaking the nailgun protocol.
    :param Exiter exiter: The Exiter instance for this run.
    :param list args: The arguments (i.e. sys.argv) for this run.
    :param dict env: The environment (i.e. os.environ) for this run.
    :param TargetRoots target_roots: The `TargetRoots` for this run.
    :param LegacyGraphHelper graph_helper: The LegacyGraphHelper instance to use for BuildGraph
                                           construction. In the event of an exception, this will be
                                           None.
    :param threading.RLock fork_lock: A lock to use during forking for thread safety.
    :param int preceding_graph_size: The size of the graph pre-warming, for stats.
    :param Exception deferred_exception: A deferred exception from the daemon's graph construction.
                                         If present, this will be re-raised in the client context.
    """
    super(DaemonPantsRunner, self).__init__(name=self._make_identity())
    self._socket = socket
    self._exiter = exiter
    self._args = args
    self._env = env
    self._target_roots = target_roots
    self._graph_helper = graph_helper
    self._fork_lock = fork_lock
    self._preceding_graph_size = preceding_graph_size
    self._deferred_exception = deferred_exception

  def _make_identity(self):
    """Generate a ProcessManager identity for a given pants run.

    This provides for a reasonably unique name e.g. 'pantsd-run-2015-09-16T23_17_56_581899'.
    """
    return 'pantsd-run-{}'.format(datetime.datetime.now().strftime('%Y-%m-%dT%H_%M_%S_%f'))

  @contextmanager
  def _tty_stdio(self):
    """Handles stdio redirection in the case of all stdio descriptors being the same tty."""
    # If all stdio is a tty, there's only one logical I/O device (the tty device). This happens to
    # be addressable as a file in OSX and Linux, so we take advantage of that and directly open the
    # character device for output redirection - eliminating the need to directly marshall any
    # interactive stdio back/forth across the socket and permitting full, correct tty control with
    # no middle-man.
    stdin_ttyname, stdout_ttyname, stderr_ttyname = NailgunProtocol.ttynames_from_env(self._env)
    assert stdin_ttyname == stdout_ttyname == stderr_ttyname, (
      'expected all stdio ttys to be the same, but instead got: {}\n'
      'please file a bug at http://github.com/pantsbuild/pants'
      .format([stdin_ttyname, stdout_ttyname, stderr_ttyname])
    )
    with open(stdin_ttyname, 'rb+wb', 0) as tty:
      tty_fileno = tty.fileno()
      with stdio_as(stdin_fd=tty_fileno, stdout_fd=tty_fileno, stderr_fd=tty_fileno):
        def finalizer():
          termios.tcdrain(tty_fileno)
        yield finalizer

  @contextmanager
  def _pipe_stdio(self, sock, stdin_isatty, stdout_isatty, stderr_isatty):
    """Handles stdio redirection in the case of pipes and/or mixed pipes and ttys."""
    stdio_writers = (
      (ChunkType.STDOUT, stdout_isatty),
      (ChunkType.STDERR, stderr_isatty)
    )
    types, ttys = zip(*(stdio_writers))
    with NailgunStreamStdinReader.open(sock, stdin_isatty) as stdin_fd,\
         NailgunStreamWriter.open_multi(sock, types, ttys) as ((stdout_fd, stderr_fd), writer),\
         stdio_as(stdout_fd=stdout_fd, stderr_fd=stderr_fd, stdin_fd=stdin_fd):
      # N.B. This will be passed to and called by the `DaemonExiter` prior to sending an
      # exit chunk, to avoid any socket shutdown vs write races.
      stdout, stderr = sys.stdout, sys.stderr
      def finalizer():
        try:
          stdout.flush()
          stderr.flush()
        finally:
          time.sleep(.001)  # HACK: Sleep 1ms in the main thread to free the GIL.
          writer.stop()
          writer.join()
          stdout.close()
          stderr.close()
      yield finalizer

  @contextmanager
  def _nailgunned_stdio(self, sock):
    """Redirects stdio to the connected socket speaking the nailgun protocol."""
    # Determine output tty capabilities from the environment.
    stdin_isatty, stdout_isatty, stderr_isatty = NailgunProtocol.isatty_from_env(self._env)

    if all((stdin_isatty, stdout_isatty, stderr_isatty)):
      with self._tty_stdio() as finalizer:
        yield finalizer
    else:
      with self._pipe_stdio(sock, stdin_isatty, stdout_isatty, stderr_isatty) as finalizer:
        yield finalizer

  def _setup_sigint_handler(self):
    """Sets up a control-c signal handler for the daemon runner context."""
    def handle_control_c(signum, frame):
      raise KeyboardInterrupt('remote client sent control-c!')
    signal.signal(signal.SIGINT, handle_control_c)

  def _raise_deferred_exc(self):
    """Raises deferred exceptions from the daemon's synchronous path in the post-fork client."""
    if self._deferred_exception:
      try:
        # Expect `_deferred_exception` to be a 3-item tuple of the values returned by sys.exc_info().
        # This permits use the 3-arg form of the `raise` statement to preserve the original traceback.
        exc_type, exc_value, exc_traceback = self._deferred_exception
        raise exc_type, exc_value, exc_traceback
      except ValueError:
        # If `_deferred_exception` isn't a 3-item tuple, treat it like a bare exception.
        raise self._deferred_exception

  def _maybe_get_client_start_time_from_env(self, env):
    client_start_time = env.pop('PANTSD_RUNTRACKER_CLIENT_START_TIME', None)
    return None if client_start_time is None else float(client_start_time)

  def run(self):
    """Fork, daemonize and invoke self.post_fork_child() (via ProcessManager)."""
    with self._fork_lock:
      self.daemonize(write_pid=False)

  def pre_fork(self):
    """Pre-fork callback executed via ProcessManager.daemonize().

    The scheduler has thread pools which need to be re-initialized after a fork: this ensures that
    when the pantsd-runner forks from pantsd, there is a working pool for any work that happens
    in that child process.
    """
    if self._graph_helper:
      self._graph_helper.scheduler.pre_fork()

  def post_fork_child(self):
    """Post-fork child process callback executed via ProcessManager.daemonize()."""
    # Set the Exiter exception hook post-fork so as not to affect the pantsd processes exception
    # hook with socket-specific behavior. Note that this intentionally points the faulthandler
    # trace stream to sys.stderr, which at this point is still a _LoggerStream object writing to
    # the `pantsd.log`. This ensures that in the event of e.g. a hung but detached pantsd-runner
    # process that the stacktrace output lands deterministically in a known place vs to a stray
    # terminal window.
    self._exiter.set_except_hook(sys.stderr)

    # Ensure anything referencing sys.argv inherits the Pailgun'd args.
    sys.argv = self._args

    # Set context in the process title.
    set_process_title('pantsd-runner [{}]'.format(' '.join(self._args)))

    # Broadcast our process group ID (in PID form - i.e. negated) to the remote client so
    # they can send signals (e.g. SIGINT) to all processes in the runners process group.
    NailgunProtocol.send_pid(self._socket, bytes(os.getpgrp() * -1))

    # Setup a SIGINT signal handler.
    self._setup_sigint_handler()

    # Invoke a Pants run with stdio redirected and a proxied environment.
    with self._nailgunned_stdio(self._socket) as finalizer, hermetic_environment_as(**self._env):
      try:
        # Setup the Exiter's finalizer.
        self._exiter.set_finalizer(finalizer)

        # Clean global state.
        clean_global_runtime_state(reset_subsystem=True)

        # Re-raise any deferred exceptions, if present.
        self._raise_deferred_exc()

        # Otherwise, conduct a normal run.
        runner = LocalPantsRunner(
          self._exiter,
          self._args,
          self._env,
          target_roots=self._target_roots,
          daemon_build_graph=self._graph_helper
        )
        runner.set_start_time(self._maybe_get_client_start_time_from_env(self._env))
        runner.set_preceding_graph_size(self._preceding_graph_size)
        runner.run()
      except KeyboardInterrupt:
        self._exiter.exit(1, msg='Interrupted by user.\n')
      except Exception:
        self._exiter.handle_unhandled_exception(add_newline=True)
      else:
        self._exiter.exit(0)
