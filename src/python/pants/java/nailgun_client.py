# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import errno
import logging
import os
import socket
import sys
import traceback
from builtins import object, str
from contextlib import contextmanager

from future.utils import binary_type

from future.utils import PY3

from pants.java.nailgun_io import NailgunStreamWriter
from pants.java.nailgun_protocol import (ChunkType, NailgunProtocol, PailgunChunkType,
                                         PailgunProtocol)
from pants.util.memo import memoized_property
from pants.util.objects import Exactly, datatype  # TODO: cache the datatype __hash__!
from pants.util.socket import RecvBufferedSocket


logger = logging.getLogger(__name__)


class NailgunClientSession(NailgunProtocol):
  """Handles a single nailgun client session."""

  def __init__(self, request):
    assert(isinstance(request, self.NailgunClientSessionInitiationRequest))
    self._request = request

  @property
  def sock(self):
    return self._request.sock

  class NailgunClientSessionInitiationRequest(datatype([
      'sock',
      'input_writer',
      'stdout',
      'stderr',
      ('exit_on_broken_pipe', bool),
  ])):

    @classmethod
    def create(cls, sock, in_file, out_file, err_file, exit_on_broken_pipe=False):

      if in_file:
        input_writer = NailgunStreamWriter(
          (in_file.fileno(),),
          sock,
          (ChunkType.STDIN,),
          ChunkType.STDIN_EOF)
      else:
        input_writer = None

      return cls(sock=sock, input_writer=input_writer, stdout=out_file, stderr=err_file,
                 exit_on_broken_pipe=exit_on_broken_pipe)

  class NailgunClientSessionExecutionRequest(datatype([
      # The fully qualified class name of the main entrypoint.
      ('main_class', binary_type),
      # Set the working directory for this command
      ('cwd', Exactly(binary_type, type(None))),
      # any arguments to pass to the main entrypoint
      ('arguments', tuple),
      # an env mapping made available to native nails via the nail context
      ('environment', dict),
  ])): pass

  class NailgunClientSessionExecutionResult(datatype([
      # If the EXIT chunk wasn't sent, this field's value is None.
      ('maybe_exit_code', Exactly(int, type(None))),
  ])): pass

  class NailgunClientSessionProtocolError(NailgunProtocol.ProtocolError): pass

  @contextmanager
  def execution_sub_session_for(self, exe_request):
    assert(isinstance(exe_request, self.NailgunClientSessionExecutionRequest))
    try:
      # Send the nailgun request synchronously -- there is no "response" to this in the base
      # NailgunProtocol, or a way to know if the remote end is doing anything (yet), so we just
      # yield a session which can have process_session() called at most once.
      self.send_request(sock=self._request.sock,
                        workdir_dir=exe_request.cwd,
                        command=exe_request.main_class,
                        *exe_request.arguments,
                        **exe_request.environment)
      yield
    except NailgunProtocol.ProtocolError as e:
      raise self.NailgunClientSessionProtocolError(
        'Error in execution sub session initialization: {}'.format(str(e)),
        e)
    finally:
      # Bad chunk types received from the server can throw PailgunProtocol.ProtocolError in
      # PailgunProtocol.iter_chunks(). This ensures the NailgunStreamWriter is always stopped.
      self._maybe_stop_input_writer()

  @property
  def _input_writer(self):
    return self._request.input_writer

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
      if e.errno == errno.EPIPE and self._request.exit_on_broken_pipe:
        sys.exit()
      # Otherwise, re-raise.
      raise

  def process_session(self, **iter_chunks_kwargs):
    """Process the outputs of the nailgun session."""
    exit_code = None
    for chunk_type, payload in self.iter_chunks(
        self.sock, return_bytes=True, break_on_exit_chunk=True, **iter_chunks_kwargs):
      if chunk_type == PailgunChunkType.STDOUT:
        self._write_flush(self._stdout, payload)
      elif chunk_type == PailgunChunkType.STDERR:
        self._write_flush(self._stderr, payload)
      elif chunk_type == PailgunChunkType.EXIT:
        self._write_flush(self._stdout)
        self._write_flush(self._stderr)
        exit_code = int(payload)
      elif chunk_type == PailgunChunkType.START_READING_INPUT:
        self._maybe_start_input_writer()
      else:
        raise self.InvalidChunkType('unrecognized chunk type {}'.format(chunk_type))
    return exit_code

  # def execute(self, exe_request, **iter_chunks_kwargs):
  #   assert(isinstance(exe_request, self.NailgunClientSessionExecutionRequest))
  #   with self.execution_sub_session_for(exe_request):
  #     exit_code = self.process_session(**iter_chunks_kwargs)
  #     return self.NailgunClientSessionExecutionResult(exit_code)

class PailgunClientSession(PailgunProtocol):

  def __init__(self, nailgun_session):
    # Delegate everything to a NailgunClientSession instance to keep the PailgunProtocol
    # inheritance.
    # TODO: figure out if this is the least confusing mixture of inheritance and composition for the
    # case of implementing/extending a binary protocol like Nailgun.
    assert(isinstance(nailgun_session, NailgunClientSession))
    self._nailgun_session = nailgun_session

  class PailgunClientSessionProtocolError(NailgunProtocol.ProtocolError): pass

  @contextmanager
  def execution_sub_session_for(self, exe_request):
    """???/so the client can be sure to have the pid and pgrp before proceeding"""
    # The base NailgunClientSession doesn't yield anything, but we are waiting for pailgun chunks.
    with self._nailgun_session.execution_sub_session_for(exe_request):
      try:
        # Block for the Pailgun-specific PID and PGRP chunks to enable signalling and log traversal.
        remote_process_info = self.parse_remote_process_initialization_sequence(
          self._nailgun_session.sock)
      except NailgunProtocol.ProtocolError as e:
        raise self.PailgunClientSessionProtocolError(
          'Error when reading remote process info: {}'.format(str(e)),
          e)

      try:
        yield remote_process_info
      except NailgunProtocol.ProtocolError as e:
        raise self.PailgunClientSessionProtocolError(
          'Error in execution sub session for remote process {}: {}'
          .format(remote_process_info, str(e)),
          e)

  def process_session(self, **iter_chunks_kwargs):
    # We return the same execution result, and don't otherwise modify anything compared to base
    # Nailgun from here on.
    self._nailgun_session.process_session(
      # Allow a 0-length read at the beginning of a chunk to denote graceful shutdown.
      none_on_zero_length_chunk=True,
      valid_chunk_types=PailgunChunkType.EXECUTION_TYPES,
      **iter_chunks_kwargs)


class NailgunClient(object):
  """A python nailgun client (see http://martiansoftware.com/nailgun for more info).

  This nailgun client can be used to issue zero or more nailgun commands (TODO: with?).
  """

  def __init__(self, request):
    assert(isinstance(request, self.NailgunClientRequest))
    self._request = request

  class NailgunClientRequest(datatype([
      ('host', binary_type),
      ('port', int),
      'stdin',
      'stdout',
      'stderr',
      ('workdir', binary_type),
      ('exit_on_broken_pipe', bool),
  ])):

    # For backwards compatibility with nails expecting the ng c client special env vars.
    ENV_DEFAULTS = dict(NAILGUN_FILESEPARATOR=os.sep, NAILGUN_PATHSEPARATOR=os.pathsep)
    DEFAULT_NG_HOST = '127.0.0.1'
    DEFAULT_NG_PORT = 2113

    def __new__(cls, host=DEFAULT_NG_HOST, port=DEFAULT_NG_PORT, ins=sys.stdin, out=None, err=None,
                workdir=None, exit_on_broken_pipe=False):
      """Creates a nailgun client request that can be ???

      :param string host: the nailgun server to contact (defaults to '127.0.0.1')
      :param int port: the port the nailgun server is listening on (defaults to the default nailgun
                       port: 2113)
      :param file ins: a file to read command standard input from (defaults to stdin) - can be None
                       in which case no input is read
      :param file out: a stream to write command standard output to (defaults to stdout)
      :param file err: a stream to write command standard error to (defaults to stderr)
      :param string workdir: the default working directory for all nailgun commands (defaults to CWD)
      :param bool exit_on_broken_pipe: whether or not to exit when `Broken Pipe` errors are
                                       encountered
      """
      return super(NailgunClient.NailgunClientRequest, cls).__new__(
        cls,
        host=binary_type(host),
        port=int(port),
        stdin=ins,
        stdout=(out or sys.stdout),
        stderr=(err or sys.stderr),
        workdir=binary_type(workdir or os.path.abspath(os.path.curdir)),
        exit_on_broken_pipe=exit_on_broken_pipe)

    @memoized_property
    def address(self):
      return (self.host, self.port)

    @memoized_property
    def address_string(self):
      return ':'.join(str(i) for i in self.address)

  class NailgunError(Exception):
    "Indicates an error interacting with a nailgun server."""

    DESCRIPTION = 'Problem talking to nailgun server'

    _MSG_FMT = """\
{description} (address: {address}): {wrapped_exc!r}
{backtrace}
"""

    def __init__(self, address, wrapped_exc, traceback=None):
      self.address = address
      self.wrapped_exc = wrapped_exc
      self.traceback = traceback or sys.exc_info()[2]

      msg = self.MSG_FMT.format(
        description=self.DESCRIPTION,
        address=self.address,
        wrapped_exc=self.wrapped_exc,
        backtrace=self.traceback(self.traceback))
      super(NailgunClient.NailgunError, self).__init__(msg, self.wrapped_exc)

    @classmethod
    def _traceback(cls, tb):
      return ''.join(traceback.format_tb(tb))

  class NailgunConnectionError(NailgunError):
    """Indicates an error upon initial connect to the nailgun server."""
    DESCRIPTION = 'Problem connecting to nailgun server'

  class NailgunExecutionError(NailgunError):
    """Indicates an error upon initial command execution on the nailgun server."""
    DESCRIPTION = 'Problem executing command on nailgun server'

  @contextmanager
  def connect_socket(self):
    """Creates a socket, connects it to this client's address and returns the connected socket.

    :yields: a connected `socket.socket`.
    :raises: `PailgunClient.NailgunConnectionError` on failure to connect.
    """
    sock = RecvBufferedSocket(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
    try:
      sock.connect(self._request.address)
      yield sock
    except (socket.error, socket.gaierror) as e:
      logger.debug('Encountered socket exception {!r} when attempting to connect to nailgun'
                   .format(e))
      raise self.NailgunConnectionError(address=self._request.address_string, wrapped_exc=e)
    finally:
      sock.close()

  @contextmanager
  def initiate_new_client_session(self):
    with self.connect_socket() as sock:
      session_init_request = NailgunClientSession.NailgunClientSessionInitiationRequest.create(
        sock,
        in_file=self._request.stdin, out_file=self._request.stdout, err_file=self._request.stderr,
        exit_on_broken_pipe=self._request.exit_on_broken_pipe)
      session = NailgunClientSession(session_init_request)
      try:
        yield session
      except (socket.error, NailgunProtocol.ProtocolError) as e:
        raise self.NailgunError(address=self._request.address_string, wrapped_exc=e)


class PailgunClient(NailgunClient):

  def __init__(self, nailgun_client):
    assert(isinstance(nailgun_client, NailgunClient))
    self._nailgun_client = nailgun_client

  class PailgunError(NailgunClient.NailgunError): pass

  @contextmanager
  def initiate_new_client_session(self):
    with self._nailgun_client.initiate_new_client_session() as nailgun_session:
      yield PailgunClientSession(nailgun_session)

  class RemotePantsSessionHandle(datatype([
      ('session', PailgunClientSession),
      ('remote_process_info', PailgunProtocol.ProcessInitialized),
  ])): pass

  @contextmanager
  def remote_pants_session(self, exe_request):
    with self.initiate_new_client_session() as nailgun_session:
      pailgun_session = PailgunClientSession(nailgun_session)
      with pailgun_session.execution_sub_session_for(exe_request) as remote_process_info:
        yield self.RemotePantsSessionHandle(pailgun_session, remote_process_info)
