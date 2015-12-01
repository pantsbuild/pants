# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import datetime
import os
import socket
import sys
import traceback
from contextlib import contextmanager

from pants.bin.exiter import Exiter
from pants.bin.pants_runner import LocalPantsRunner
from pants.java.nailgun_io import NailgunStreamReader, NailgunStreamWriter
from pants.java.nailgun_protocol import ChunkType, NailgunProtocol
from pants.pantsd.process_manager import ProcessManager
from pants.util.contextutil import stdio_as


class DaemonExiter(Exiter):
  """An Exiter that emits unhandled tracebacks and exit codes via the Nailgun protocol."""

  def __init__(self, socket):
    super(DaemonExiter, self).__init__()
    self._socket = socket

  def _shutdown_socket(self):
    """Shutdown and close the connected socket."""
    try:
      self._socket.shutdown(socket.SHUT_WR)
    except socket.error:
      pass
    finally:
      self._socket.close()

  def exit(self, result=0, msg=None):
    """Exit the runtime."""
    try:
      # Write a final message to stderr if present.
      if msg:
        NailgunProtocol.write_chunk(self._socket, ChunkType.STDERR, msg)

      # Send an Exit chunk with the result.
      NailgunProtocol.write_chunk(self._socket, ChunkType.EXIT, str(result).encode('ascii'))

      # Shutdown the connected socket.
      self._shutdown_socket()
    finally:
      # N.B. Assuming a fork()'d child, os._exit(0) here to avoid the routine sys.exit() behavior.
      os._exit(0)


class DaemonPantsRunner(ProcessManager):
  """A daemonizing PantsRunner that speaks the nailgun protocol to a remote client.

  N.B. this class is primarily used by the PailgunService in pantsd.
  """

  def __init__(self, socket, exiter, args, env):
    """
    :param socket socket: A connected socket capable of speaking the nailgun protocol.
    :param Exiter exiter: The Exiter instance for this run.
    :param list args: The arguments (i.e. sys.argv) for this run.
    :param dict env: The environment (i.e. os.environ) for this run.
    """
    super(DaemonPantsRunner, self).__init__(name=self._make_identity())
    self._socket = socket
    self._exiter = exiter
    self._args = args
    self._env = env

  def _make_identity(self):
    """Generate a ProcessManager identity for a given pants run.

    This provides for a reasonably unique name e.g. 'pantsd-run-2015-09-16T23_17_56_581899'.
    """
    return 'pantsd-run-{}'.format(datetime.datetime.now().strftime('%Y-%m-%dT%H_%M_%S_%f'))

  @contextmanager
  def _nailgunned_stdio(self, sock):
    """Redirects stdio to the connected socket speaking the nailgun protocol."""
    # Determine output tty capabilities from the environment.
    _, stdout_isatty, stderr_isatty = NailgunProtocol.isatty_from_env(self._env)

    # TODO(kwlzn): Implement remote input reading and fix the non-fork()-safe sys.stdin reference
    # in NailgunClient to enable support for interactive goals like `repl` etc.

    # Construct StreamWriters for stdout, stderr.
    streams = (
      NailgunStreamWriter(sock, ChunkType.STDOUT, isatty=stdout_isatty),
      NailgunStreamWriter(sock, ChunkType.STDERR, isatty=stderr_isatty)
    )

    # Launch the stdin StreamReader and redirect stdio.
    with stdio_as(*streams):
      yield

  def run(self):
    """Fork, daemonize and invoke self.post_fork_child() (via ProcessManager)."""
    self.daemonize(write_pid=False)

  def post_fork_child(self):
    """Post-fork child process callback executed via ProcessManager.daemonize()."""
    # Set the Exiter exception hook post-fork so as not to affect the pantsd processes exception
    # hook with socket-specific behavior.
    self._exiter.set_except_hook()

    # Invoke a Pants run with stdio redirected.
    with self._nailgunned_stdio(self._socket):
      try:
        LocalPantsRunner(self._exiter, self._args, self._env).run()
      except Exception:
        self._exiter.exit(1, msg=traceback.format_exc())
      else:
        self._exiter.exit(0)
