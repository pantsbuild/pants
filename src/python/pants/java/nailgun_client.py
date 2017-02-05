# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import logging
import os
import signal
import socket
import sys

from pants.java.nailgun_io import NailgunStreamReader
from pants.java.nailgun_protocol import ChunkType, NailgunProtocol
from pants.util.socket import RecvBufferedSocket


logger = logging.getLogger(__name__)


class NailgunClientSession(NailgunProtocol):
  """Handles a single nailgun client session."""

  def __init__(self, sock, in_fd, out_fd, err_fd, exit_on_broken_pipe=False):
    self._sock = sock
    self._input_reader = NailgunStreamReader(in_fd, self._sock) if in_fd else None
    self._stdout = out_fd
    self._stderr = err_fd
    self._exit_on_broken_pipe = exit_on_broken_pipe
    self.remote_pid = None

  def _maybe_start_input_reader(self):
    if self._input_reader:
      self._input_reader.start()

  def _maybe_stop_input_reader(self):
    if self._input_reader:
      self._input_reader.stop()

  def _write_flush(self, fd, payload=None):
    """Write a payload to a given fd (if provided) and flush the fd."""
    try:
      if payload:
        fd.write(payload)
      fd.flush()
    except (IOError, OSError) as e:
      # If a `Broken Pipe` is encountered during a stdio fd write, we're headless - bail.
      if e.errno == errno.EPIPE and self._exit_on_broken_pipe:
        sys.exit()
      # Otherwise, re-raise.
      raise

  def _process_session(self):
    """Process the outputs of the nailgun session."""
    try:
      for chunk_type, payload in self.iter_chunks(self._sock, return_bytes=True):
        if chunk_type == ChunkType.STDOUT:
          self._write_flush(self._stdout, payload)
        elif chunk_type == ChunkType.STDERR:
          self._write_flush(self._stderr, payload)
        elif chunk_type == ChunkType.EXIT:
          self._write_flush(self._stdout)
          self._write_flush(self._stderr)
          return int(payload)
        elif chunk_type == ChunkType.PID:
          self.remote_pid = int(payload)
        elif chunk_type == ChunkType.START_READING_INPUT:
          self._maybe_start_input_reader()
        else:
          raise self.ProtocolError('received unexpected chunk {} -> {}'.format(chunk_type, payload))
    finally:
      # Bad chunk types received from the server can throw NailgunProtocol.ProtocolError in
      # NailgunProtocol.iter_chunks(). This ensures the NailgunStreamReader is always stopped.
      self._maybe_stop_input_reader()

  def execute(self, working_dir, main_class, *arguments, **environment):
    # Send the nailgun request.
    self.send_request(self._sock, working_dir, main_class, *arguments, **environment)

    # Process the remainder of the nailgun session.
    return self._process_session()


class NailgunClient(object):
  """A python nailgun client (see http://martiansoftware.com/nailgun for more info)."""

  class NailgunError(Exception):
    """Indicates an error interacting with a nailgun server."""

  class NailgunConnectionError(NailgunError):
    """Indicates an error upon initial connect to the nailgun server."""

  # For backwards compatibility with nails expecting the ng c client special env vars.
  ENV_DEFAULTS = dict(NAILGUN_FILESEPARATOR=os.sep, NAILGUN_PATHSEPARATOR=os.pathsep)
  DEFAULT_NG_HOST = '127.0.0.1'
  DEFAULT_NG_PORT = 2113

  def __init__(self, host=DEFAULT_NG_HOST, port=DEFAULT_NG_PORT, ins=sys.stdin, out=None, err=None,
               workdir=None, exit_on_broken_pipe=False):
    """Creates a nailgun client that can be used to issue zero or more nailgun commands.

    :param string host: the nailgun server to contact (defaults to '127.0.0.1')
    :param int port: the port the nailgun server is listening on (defaults to the default nailgun
                     port: 2113)
    :param file ins: a file to read command standard input from (defaults to stdin) - can be None
                     in which case no input is read
    :param file out: a stream to write command standard output to (defaults to stdout)
    :param file err: a stream to write command standard error to (defaults to stderr)
    :param string workdir: the default working directory for all nailgun commands (defaults to CWD)
    :param bool exit_on_broken_pipe: whether or not to exit when `Broken Pipe` errors are encountered.
    """
    self._host = host
    self._port = port
    self._stdin = ins
    self._stdout = out or sys.stdout
    self._stderr = err or sys.stderr
    self._workdir = workdir or os.path.abspath(os.path.curdir)
    self._exit_on_broken_pipe = exit_on_broken_pipe
    self._session = None

  def try_connect(self):
    """Creates a socket, connects it to the nailgun and returns the connected socket.

    :returns: a connected `socket.socket`.
    :raises: `NailgunClient.NailgunConnectionError` on failure to connect.
    """
    sock = RecvBufferedSocket(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
    try:
      sock.connect((self._host, self._port))
    except (socket.error, socket.gaierror) as e:
      logger.debug('Encountered socket exception {!r} when attempting connect to nailgun'.format(e))
      sock.close()
      raise self.NailgunConnectionError(
        'Problem connecting to nailgun server at {}:{}: {!r}'.format(self._host, self._port, e))
    else:
      return sock

  def send_control_c(self):
    """Sends SIGINT to a nailgun server using pid information from the active session."""
    if self._session and self._session.remote_pid is not None:
      os.kill(self._session.remote_pid, signal.SIGINT)

  def execute(self, main_class, cwd=None, *args, **environment):
    """Executes the given main_class with any supplied args in the given environment.

    :param string main_class: the fully qualified class name of the main entrypoint
    :param string cwd: Set the working directory for this command
    :param list args: any arguments to pass to the main entrypoint
    :param dict environment: an env mapping made available to native nails via the nail context
    :returns: the exit code of the main_class.
    """
    environment = dict(self.ENV_DEFAULTS.items() + environment.items())
    cwd = cwd or self._workdir

    # N.B. This can throw NailgunConnectionError (catchable via NailgunError).
    sock = self.try_connect()

    self._session = NailgunClientSession(sock,
                                         self._stdin,
                                         self._stdout,
                                         self._stderr,
                                         self._exit_on_broken_pipe)
    try:
      return self._session.execute(cwd, main_class, *args, **environment)
    except socket.error as e:
      raise self.NailgunError('Problem communicating with nailgun server at {}:{}: {!r}'
                              .format(self._host, self._port, e))
    except NailgunProtocol.ProtocolError as e:
      raise self.NailgunError('Problem in nailgun protocol with nailgun server at {}:{}: {!r}'
                              .format(self._host, self._port, e))
    finally:
      sock.close()
      self._session = None

  def __repr__(self):
    return 'NailgunClient(host={!r}, port={!r}, workdir={!r})'.format(self._host,
                                                                      self._port,
                                                                      self._workdir)
