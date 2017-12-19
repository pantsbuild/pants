# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import datetime
import os
import signal
import sys
import time
from contextlib import contextmanager

from setproctitle import setproctitle as set_process_title

from pants.base.exiter import Exiter
from pants.bin.local_pants_runner import LocalPantsRunner
from pants.init.util import clean_global_runtime_state
from pants.java.nailgun_io import NailgunStreamStdinReader, NailgunStreamWriter
from pants.java.nailgun_protocol import ChunkType, NailgunProtocol
from pants.pantsd.process_manager import ProcessManager
from pants.util.contextutil import HardSystemExit, stdio_as
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

  def __init__(self, socket, exiter, args, env, graph_helper, fork_lock, deferred_exception=None):
    """
    :param socket socket: A connected socket capable of speaking the nailgun protocol.
    :param Exiter exiter: The Exiter instance for this run.
    :param list args: The arguments (i.e. sys.argv) for this run.
    :param dict env: The environment (i.e. os.environ) for this run.
    :param LegacyGraphHelper graph_helper: The LegacyGraphHelper instance to use for BuildGraph
                                           construction. In the event of an exception, this will be
                                           None.
    :param threading.RLock fork_lock: A lock to use during forking for thread safety.
    :param Exception deferred_exception: A deferred exception from the daemon's graph construction.
                                         If present, this will be re-raised in the client context.
    """
    super(DaemonPantsRunner, self).__init__(name=self._make_identity())
    self._socket = socket
    self._exiter = exiter
    self._args = args
    self._env = env
    self._graph_helper = graph_helper
    self._fork_lock = fork_lock
    self._deferred_exception = deferred_exception

  def _make_identity(self):
    """Generate a ProcessManager identity for a given pants run.

    This provides for a reasonably unique name e.g. 'pantsd-run-2015-09-16T23_17_56_581899'.
    """
    return 'pantsd-run-{}'.format(datetime.datetime.now().strftime('%Y-%m-%dT%H_%M_%S_%f'))

  @contextmanager
  def _nailgunned_stdio(self, sock):
    """Redirects stdio to the connected socket speaking the nailgun protocol."""
    # Determine output tty capabilities from the environment.
    stdin_isatty, stdout_isatty, stderr_isatty = NailgunProtocol.isatty_from_env(self._env)

    # Launch a thread to read stdin data from the socket (the only messages expected from the client
    # for the remainder of the protocol), and threads to copy from stdout/stderr pipes onto the
    # socket.
    with NailgunStreamWriter.open_multi(
           sock,
           (ChunkType.STDOUT, ChunkType.STDERR),
           None,
           (stdout_isatty, stderr_isatty)
         ) as ((stdout, stderr), writer),\
         NailgunStreamStdinReader.open(sock, stdin_isatty) as stdin,\
         stdio_as(stdout_fd=stdout.fileno(), stderr_fd=stderr.fileno(), stdin_fd=stdin.fileno()):
      # N.B. This will be passed to and called by the `DaemonExiter` prior to sending an
      # exit chunk, to avoid any socket shutdown vs write races.
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

    # Broadcast our pid to the remote client so they can send us signals (i.e. SIGINT).
    NailgunProtocol.send_pid(self._socket, bytes(os.getpid()))

    # Setup a SIGINT signal handler.
    self._setup_sigint_handler()

    # Invoke a Pants run with stdio redirected.
    with self._nailgunned_stdio(self._socket) as finalizer:
      try:
        # Setup the Exiter's finalizer.
        self._exiter.set_finalizer(finalizer)

        # Clean global state.
        clean_global_runtime_state(reset_subsystem=True)

        # Re-raise any deferred exceptions, if present.
        self._raise_deferred_exc()

        # Otherwise, conduct a normal run.
        LocalPantsRunner(self._exiter, self._args, self._env, self._graph_helper).run()
      except KeyboardInterrupt:
        self._exiter.exit(1, msg='Interrupted by user.\n')
      except Exception:
        self._exiter.handle_unhandled_exception(add_newline=True)
      else:
        self._exiter.exit(0)
