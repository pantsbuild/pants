# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import os
import sys
import termios
import time
from builtins import open, zip
from contextlib import contextmanager

from future.utils import raise_with_traceback

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink, SignalHandler
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, Exiter
from pants.bin.local_pants_runner import LocalPantsRunner
from pants.init.logging import encapsulated_global_logger, setup_logging_from_options
from pants.init.util import clean_global_runtime_state
from pants.java.nailgun_io import NailgunStreamStdinReader, NailgunStreamWriter
from pants.java.nailgun_protocol import ChunkType, NailgunProtocol
from pants.pantsd.process_manager import ProcessManager
from pants.util.contextutil import hermetic_environment_as, stdio_as
from pants.util.socket import teardown_socket


class DaemonSignalHandler(SignalHandler):

  def handle_sigint(self, signum, _frame):
    write_to_file("DSH received sigint!")
    self.daemon.shutdown()
    raise KeyboardInterrupt('remote client sent control-c!')

  def handle_sigterm(self, signum, _frame):
    try:
      self.daemon.shutdown()
    except Exception:
      pass


def write_to_file(msg):
  with open('/tmp/logs', 'a') as f:
    f.write('{}\n'.format(msg))


class NoopExiter(Exiter):
  def exit(self, result, *args, **kwargs):
    if result != 0:
      write_to_file("LPR, Exiting with code {}!".format(result))
      raise _GracefulTerminationException(result)


class DaemonExiter(Exiter):
  """An Exiter that emits unhandled tracebacks and exit codes via the Nailgun protocol.

  TODO: This no longer really follows the Exiter API, per-se (or at least, it doesn't call super).
  """

  def __init__(self, socket):
    # N.B. Assuming a fork()'d child, cause os._exit to be called here to avoid the routine
    # sys.exit behavior.
    # TODO: The behavior we're avoiding with the use of os._exit should be described and tested.
    super(DaemonExiter, self).__init__(exiter=os._exit)
    self._socket = socket
    self._finalizer = None

  def set_finalizer(self, finalizer):
    """Sets a finalizer that will be called before exiting."""
    self._finalizer = finalizer

  def exit(self, result=0, msg=None, *args, **kwargs):
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

    write_to_file("DPR, Exiting with code {} and msg {}".format(result, msg))

    # Write a final message to stderr if present.
    if msg:
      NailgunProtocol.send_stderr(self._socket, msg)

    # Send an Exit chunk with the result.
    NailgunProtocol.send_exit_with_code(self._socket, result)

    # Shutdown the connected socket.
    teardown_socket(self._socket)


class _GracefulTerminationException(Exception):
  """Allows for deferring the returning of the exit code of prefork work until post fork.

  TODO: Once the fork boundary is removed in #7390, this class can be replaced by directly exiting
  with the relevant exit code.
  """

  def __init__(self, exit_code=PANTS_FAILED_EXIT_CODE):
    """
    :param int exit_code: an optional exit code (defaults to PANTS_FAILED_EXIT_CODE)
    """
    super(_GracefulTerminationException, self).__init__('Terminated with {}'.format(exit_code))

    if exit_code == PANTS_SUCCEEDED_EXIT_CODE:
      raise ValueError(
        "Cannot create _GracefulTerminationException with a successful exit code of {}"
        .format(PANTS_SUCCEEDED_EXIT_CODE))

    self._exit_code = exit_code

  @property
  def exit_code(self):
    return self._exit_code


class DaemonPantsRunner(ProcessManager):
  """A daemonizing PantsRunner that speaks the nailgun protocol to a remote client.

  N.B. this class is primarily used by the PailgunService in pantsd.
  """

  @classmethod
  def create(cls, sock, args, env, services, scheduler_service):
    try:
      # N.B. This will temporarily redirect stdio in the daemon's pre-fork context
      # to the nailgun session. We'll later do this a second time post-fork, because
      # threads.
      with cls.nailgunned_stdio(sock, env, handle_stdin=False):
        options, _, options_bootstrapper = LocalPantsRunner.parse_options(args, env)
        subprocess_dir = options.for_global_scope().pants_subprocessdir
        graph_helper, target_roots, exit_code = scheduler_service.prefork(options, options_bootstrapper)
        deferred_exc = None if exit_code == PANTS_SUCCEEDED_EXIT_CODE else _GracefulTerminationException(exit_code)
    except Exception:
      deferred_exc = sys.exc_info()
      graph_helper = None
      target_roots = None
      options_bootstrapper = None
      # N.B. This will be overridden with the correct value if options
      # parsing is successful - otherwise it permits us to run just far
      # enough to raise the deferred exception.
      subprocess_dir = os.path.join(get_buildroot(), '.pids')

    return cls(
      sock,
      args,
      env,
      graph_helper,
      target_roots,
      services,
      subprocess_dir,
      options_bootstrapper,
      deferred_exc
    )

  def __init__(self, socket, args, env, graph_helper, target_roots, services,
               metadata_base_dir, options_bootstrapper, deferred_exc):
    """
    :param socket socket: A connected socket capable of speaking the nailgun protocol.
    :param list args: The arguments (i.e. sys.argv) for this run.
    :param dict env: The environment (i.e. os.environ) for this run.
    :param LegacyGraphSession graph_helper: The LegacyGraphSession instance to use for BuildGraph
                                            construction. In the event of an exception, this will be
                                            None.
    :param TargetRoots target_roots: The `TargetRoots` for this run.
    :param PantsServices services: The PantsServices that are currently running.
    :param str metadata_base_dir: The ProcessManager metadata_base_dir from options.
    :param OptionsBootstrapper options_bootstrapper: An OptionsBootstrapper to reuse.
    :param Exception deferred_exception: A deferred exception from the daemon's pre-fork context.
                                         If present, this will be re-raised in the client context.
    """
    super(DaemonPantsRunner, self).__init__(
      name=self._make_identity(),
      metadata_base_dir=metadata_base_dir
    )
    self._socket = socket
    self._args = args
    self._env = env
    self._graph_helper = graph_helper
    self._target_roots = target_roots
    self._services = services
    self._options_bootstrapper = options_bootstrapper
    self._deferred_exception = deferred_exc

    self._exiter = DaemonExiter(socket)

  def _make_identity(self):
    """Generate a ProcessManager identity for a given pants run.

    This provides for a reasonably unique name e.g. 'pantsd-run-2015-09-16T23_17_56_581899'.
    """
    return 'pantsd-run-{}'.format(datetime.datetime.now().strftime('%Y-%m-%dT%H_%M_%S_%f'))

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
  def _pipe_stdio(cls, sock, stdin_isatty, stdout_isatty, stderr_isatty, handle_stdin):
    """Handles stdio redirection in the case of pipes and/or mixed pipes and ttys."""
    stdio_writers = (
      (ChunkType.STDOUT, stdout_isatty),
      (ChunkType.STDERR, stderr_isatty)
    )
    types, ttys = zip(*(stdio_writers))

    @contextmanager
    def maybe_handle_stdin(want):
      if want:
        # TODO: Launching this thread pre-fork to handle @rule input currently results
        # in an unhandled SIGILL in `src/python/pants/engine/scheduler.py, line 313 in pre_fork`.
        # More work to be done here in https://github.com/pantsbuild/pants/issues/6005
        with NailgunStreamStdinReader.open(sock, stdin_isatty) as fd:
          yield fd
      else:
        with open('/dev/null', 'rb') as fh:
          yield fh.fileno()

    with maybe_handle_stdin(handle_stdin) as stdin_fd,\
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

  # TODO: there's no testing for this method, and this caused a user-visible failure -- see #7008!
  def _raise_deferred_exc(self):
    """Raises deferred exceptions from the daemon's synchronous path in the post-fork client."""
    if self._deferred_exception:
      try:
        exc_type, exc_value, exc_traceback = self._deferred_exception
        raise_with_traceback(exc_value, exc_traceback)
      except TypeError:
        # If `_deferred_exception` isn't a 3-item tuple (raising a TypeError on the above
        # destructuring), treat it like a bare exception.
        raise self._deferred_exception

  def _maybe_get_client_start_time_from_env(self, env):
    client_start_time = env.pop('PANTSD_RUNTRACKER_CLIENT_START_TIME', None)
    return None if client_start_time is None else float(client_start_time)

  def run(self):
    """Fork, daemonize and invoke self.post_fork_child() (via ProcessManager).

    The scheduler has thread pools which need to be re-initialized after a fork: this ensures that
    when the pantsd-runner forks from pantsd, there is a working pool for any work that happens
    in that child process.
    """
    # Ensure anything referencing sys.argv inherits the Pailgun'd args.
    sys.argv = self._args

    # Broadcast our process group ID (in PID form - i.e. negated) to the remote client so
    # they can send signals (e.g. SIGINT) to all processes in the runners process group.
    NailgunProtocol.send_pid(self._socket, os.getpid())
    NailgunProtocol.send_pgrp(self._socket, os.getpgrp() * -1)

    # Invoke a Pants run with stdio redirected and a proxied environment.
    with self.nailgunned_stdio(self._socket, self._env) as finalizer, \
      hermetic_environment_as(**self._env), \
      encapsulated_global_logger():
      try:
        # Clean global state.
        clean_global_runtime_state(reset_subsystem=True)

        # Setup the Exiter's finalizer.
        self._exiter.set_finalizer(finalizer)

        # Re-raise any deferred exceptions, if present.
        self._raise_deferred_exc()
        bootstrap_options = self._options_bootstrapper.get_bootstrap_options().for_global_scope()
        setup_logging_from_options(bootstrap_options)
        # Otherwise, conduct a normal run.
        runner = LocalPantsRunner.create(
          NoopExiter(),
          self._args,
          self._env,
          self._target_roots,
          self._graph_helper,
          self._options_bootstrapper,
        )
        runner.set_start_time(self._maybe_get_client_start_time_from_env(self._env))

        # Re-raise any deferred exceptions, if present.
        self._raise_deferred_exc()

        runner.run()
        write_to_file("DPR, After the run has finished")
      except KeyboardInterrupt:
        write_to_file("DPR, Keyboard interrupt in DPR")
        self._exiter.exit_and_fail('Interrupted by user.\n')
      except _GracefulTerminationException as e:
        write_to_file("DPR, GracefulTerminationException")
        ExceptionSink.log_exception(
          'Encountered graceful termination exception {}; exiting'.format(e))
        self._exiter.exit(e.exit_code)
      except Exception as e:
        write_to_file("DPR, exception in DPR!")

        # LocalPantsRunner.set_start_time resets the global exiter,
        # which used to be okay, because it was process-local,
        # but now we need to un-reset it here.
        ExceptionSink.reset_exiter(self._exiter)
        # TODO: We override sys.excepthook above when we call ExceptionSink.set_exiter(). That
        # excepthook catches `SignalHandledNonLocalExit`s from signal handlers, which isn't
        # happening here, so something is probably overriding the excepthook. By catching Exception
        # and calling this method, we emulate the normal, expected sys.excepthook override.
        self._exiter.exit(e.errno)
      else:
        self._exiter.exit(PANTS_SUCCEEDED_EXIT_CODE)
