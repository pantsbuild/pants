# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import errno
import logging
import os
import socket
import sys
from builtins import object, str

from pants.java.nailgun_io import NailgunStreamWriter
from pants.java.nailgun_protocol import ChunkType, NailgunProtocol
from pants.util.osutil import safe_kill
from pants.util.socket import RecvBufferedSocket


logger = logging.getLogger(__name__)


class NailgunClientSession(NailgunProtocol):
  """Handles a single nailgun client session."""

  def __init__(self, sock, in_file, out_file, err_file, exit_on_broken_pipe=False,
               remote_pid_callback=None, remote_pgrp_callback=None):
    """
    :param bool exit_on_broken_pipe: whether or not to exit when `Broken Pipe` errors are
                encountered
    :param remote_pid_callback: Callback to run when a pid chunk is received from a remote client.
    :param remote_pgrp_callback: Callback to run when a pgrp (process group) chunk is received from
                                 a remote client.
    """
    self._sock = sock
    self._input_writer = None if not in_file else NailgunStreamWriter(
      (in_file.fileno(),),
      self._sock,
      (ChunkType.STDIN,),
      ChunkType.STDIN_EOF
    )
    self._stdout = out_file
    self._stderr = err_file
    self._exit_on_broken_pipe = exit_on_broken_pipe
    self.remote_pid = None
    self.remote_pgrp = None
    self._remote_pid_callback = remote_pid_callback
    self._remote_pgrp_callback = remote_pgrp_callback

  def _maybe_start_input_writer(self):
    if self._input_writer and not self._input_writer.is_alive():
      self._input_writer.start()

  def _maybe_stop_input_writer(self):
    if self._input_writer and self._input_writer.is_alive():
      self._input_writer.stop()
      self._input_writer.join()

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
        # TODO(#6579): assert that we have at this point received all the chunk types in
        # ChunkType.REQUEST_TYPES, then require PID and PGRP (exactly once?), and then allow any of
        # ChunkType.EXECUTION_TYPES.
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
          if self._remote_pid_callback:
            self._remote_pid_callback(self.remote_pid)
        elif chunk_type == ChunkType.PGRP:
          self.remote_pgrp = int(payload)
          if self._remote_pgrp_callback:
            self._remote_pgrp_callback(self.remote_pgrp)
        elif chunk_type == ChunkType.START_READING_INPUT:
          self._maybe_start_input_writer()
        else:
          raise self.ProtocolError('received unexpected chunk {} -> {}'.format(chunk_type, payload))
    finally:
      # Bad chunk types received from the server can throw NailgunProtocol.ProtocolError in
      # NailgunProtocol.iter_chunks(). This ensures the NailgunStreamWriter is always stopped.
      self._maybe_stop_input_writer()

  def execute(self, working_dir, main_class, *arguments, **environment):
    # Send the nailgun request.
    self.send_request(self._sock, working_dir, main_class, *arguments, **environment)

    # Process the remainder of the nailgun session.
    return self._process_session()


class NailgunClient(object):
  """A python nailgun client (see http://martiansoftware.com/nailgun for more info)."""

  class NailgunError(Exception):
    """Indicates an error interacting with a nailgun server."""

    DESCRIPTION = 'Problem talking to nailgun server'

    _MSG_FMT = """\
{description} (address: {address}, remote_pid={pid}, remote_pgrp={pgrp}): {wrapped_exc!r}\
"""

    def __init__(self, address, pid, pgrp, wrapped_exc, traceback):
      self.address = address
      self.pid = pid
      self.pgrp = pgrp
      self.wrapped_exc = wrapped_exc
      self.traceback = traceback

      # TODO: these should be ensured to be non-None in NailgunClientSession!
      if self.pid is not None:
        pid_msg = str(self.pid)
      else:
        pid_msg = '<remote PID chunk not yet received!>'
      if self.pgrp is not None:
        pgrp_msg = str(self.pgrp)
      else:
        pgrp_msg = '<remote PGRP chunk not yet received!>'

      msg = self._MSG_FMT.format(
        description=self.DESCRIPTION,
        address=self.address,
        pid=pid_msg,
        pgrp=pgrp_msg,
        wrapped_exc=self.wrapped_exc)
      super(NailgunClient.NailgunError, self).__init__(msg, self.wrapped_exc)

  class NailgunConnectionError(NailgunError):
    """Indicates an error upon initial connect to the nailgun server."""
    DESCRIPTION = 'Problem connecting to nailgun server'

  class NailgunExecutionError(NailgunError):
    """Indicates an error upon initial command execution on the nailgun server."""
    DESCRIPTION = 'Problem executing command on nailgun server'

  # For backwards compatibility with nails expecting the ng c client special env vars.
  ENV_DEFAULTS = dict(NAILGUN_FILESEPARATOR=os.sep, NAILGUN_PATHSEPARATOR=os.pathsep)
  DEFAULT_NG_HOST = '127.0.0.1'
  DEFAULT_NG_PORT = 2113

  def __init__(self, host=DEFAULT_NG_HOST, port=DEFAULT_NG_PORT, ins=sys.stdin, out=None, err=None,
               workdir=None, exit_on_broken_pipe=False, expects_pid=False):
    """Creates a nailgun client that can be used to issue zero or more nailgun commands.

    :param string host: the nailgun server to contact (defaults to '127.0.0.1')
    :param int port: the port the nailgun server is listening on (defaults to the default nailgun
                     port: 2113)
    :param file ins: a file to read command standard input from (defaults to stdin) - can be None
                     in which case no input is read
    :param file out: a stream to write command standard output to (defaults to stdout)
    :param file err: a stream to write command standard error to (defaults to stderr)
    :param string workdir: the default working directory for all nailgun commands (defaults to CWD)
    :param bool exit_on_broken_pipe: whether or not to exit when `Broken Pipe` errors are encountered
    :param bool expects_pid: Whether or not to expect a PID from the server (only true for pantsd)
    """
    self._host = host
    self._port = port
    self._address = (host, port)
    self._address_string = ':'.join(str(i) for i in self._address)
    self._stdin = ins
    self._stdout = out or sys.stdout
    self._stderr = err or sys.stderr
    self._workdir = workdir or os.path.abspath(os.path.curdir)
    self._exit_on_broken_pipe = exit_on_broken_pipe
    self._expects_pid = expects_pid
    # Mutable session state.
    self._session = None
    self._current_remote_pid = None
    self._current_remote_pgrp = None

  def _receive_remote_pid(self, pid):
    self._current_remote_pid = pid

  def _receive_remote_pgrp(self, pgrp):
    self._current_remote_pgrp = pgrp

  def _maybe_last_pid(self):
    return self._current_remote_pid

  def _maybe_last_pgrp(self):
    return self._current_remote_pgrp

  def try_connect(self):
    """Creates a socket, connects it to the nailgun and returns the connected socket.

    :returns: a connected `socket.socket`.
    :raises: `NailgunClient.NailgunConnectionError` on failure to connect.
    """
    sock = RecvBufferedSocket(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
    try:
      sock.connect(self._address)
    except (socket.error, socket.gaierror) as e:
      logger.debug('Encountered socket exception {!r} when attempting connect to nailgun'.format(e))
      sock.close()
      raise self.NailgunConnectionError(
        address=self._address_string,
        pid=self._maybe_last_pid(),
        pgrp=self._maybe_last_pgrp(),
        wrapped_exc=e,
        traceback=sys.exc_info()[2],
      )
    else:
      return sock

  def maybe_send_signal(self, signum, include_pgrp=True):
    """Send the signal `signum` send if the PID and/or PGRP chunks have been received.

    No error is raised if the pid or pgrp are None or point to an already-dead process.
    """
    remote_pid = self._maybe_last_pid()
    if remote_pid is not None:
      safe_kill(remote_pid, signum)
    if include_pgrp:
      remote_pgrp = self._maybe_last_pgrp()
      if remote_pgrp:
        safe_kill(remote_pgrp, signum)

  def execute(self, main_class, cwd=None, *args, **environment):
    """Executes the given main_class with any supplied args in the given environment.

    :param string main_class: the fully qualified class name of the main entrypoint
    :param string cwd: Set the working directory for this command
    :param list args: any arguments to pass to the main entrypoint
    :param dict environment: an env mapping made available to native nails via the nail context
    :returns: the exit code of the main_class.
    :raises: :class:`NailgunClient.NailgunError` if there was an error during execution.
    """
    environment = dict(**environment)
    environment.update(self.ENV_DEFAULTS)
    cwd = cwd or self._workdir

    sock = self.try_connect()

    # TODO(#6579): NailgunClientSession currently requires callbacks because it can't depend on
    # having received these chunks, so we need to avoid clobbering these fields until we initialize
    # a new session.
    self._current_remote_pid = None
    self._current_remote_pgrp = None
    self._session = NailgunClientSession(
      sock=sock,
      in_file=self._stdin,
      out_file=self._stdout,
      err_file=self._stderr,
      exit_on_broken_pipe=self._exit_on_broken_pipe,
      remote_pid_callback=self._receive_remote_pid,
      remote_pgrp_callback=self._receive_remote_pgrp)
    try:
      return self._session.execute(cwd, main_class, *args, **environment)
    except socket.error as e:
      raise self.NailgunError(
        address=self._address_string,
        pid=self._maybe_last_pid(),
        pgrp=self._maybe_last_pgrp(),
        wrapped_exc=e,
        traceback=sys.exc_info()[2]
      )
    except NailgunProtocol.ProtocolError as e:
      raise self.NailgunError(
        address=self._address_string,
        pid=self._maybe_last_pid(),
        pgrp=self._maybe_last_pgrp(),
        wrapped_exc=e,
        traceback=sys.exc_info()[2]
      )
    finally:
      sock.close()
      self._session = None

  def __repr__(self):
    return 'NailgunClient(host={!r}, port={!r}, workdir={!r})'.format(self._host,
                                                                      self._port,
                                                                      self._workdir)
