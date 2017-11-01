# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import io
import os
import select
import socket
import threading
from contextlib import contextmanager

from pants.java.nailgun_protocol import ChunkType, NailgunProtocol


@contextmanager
def _pipe(isatty):
  r_fd, w_fd = os.openpty() if isatty else os.pipe()
  try:
    yield os.fdopen(r_fd, 'r'), os.fdopen(w_fd, 'w')
  finally:
    os.close(r_fd)
    os.close(w_fd)


class NailgunStreamStdinReader(threading.Thread):
  """Reads Nailgun 'stdin' chunks on a socket and writes them to an output file-like.

  Because a Nailgun server only ever receives STDIN and STDIN_EOF ChunkTypes after initial
  setup, this thread executes all reading from a server socket.

  Runs until the socket is closed.
  """

  def __init__(self, sock, write_handle):
    """
    :param socket sock: the socket to read nailgun protocol chunks from.
    """
    super(NailgunStreamStdinReader, self).__init__()
    self.daemon = True
    self._socket = sock
    self._write_handle = write_handle

  @classmethod
  @contextmanager
  def open(cls, sock, isatty=False):
    with _pipe(isatty) as (read_handle, write_handle):
      reader = NailgunStreamStdinReader(sock, write_handle)
      reader.start()
      try:
        yield read_handle
      finally:
        reader._try_close()

  def _try_close(self):
    try:
      self._socket.close()
    except Exception:
      pass

  def run(self):
    for chunk_type, payload in NailgunProtocol.iter_chunks(self._socket, return_bytes=True):
      if chunk_type == ChunkType.STDIN:
        self._write_handle.write(payload)
        self._write_handle.flush()
      elif chunk_type == ChunkType.STDIN_EOF:
        self._write_handle.close()
        break
      else:
        self._try_close()
        raise Exception('received unexpected chunk {} -> {}: closing.'.format(chunk_type, payload))


class NailgunStreamWriter(threading.Thread):
  """Reads input from an input fd and writes Nailgun chunks on a socket.

  Should generally be managed with the `open` classmethod contextmanager, which will create
  a pipe and provide its writing end to the caller.
  """

  SELECT_TIMEOUT = 1

  def __init__(self, in_file, sock, chunk_type, chunk_eof_type, buf_size=None, select_timeout=None):
    """
    :param file in_file: the input file-like to read from.
    :param socket sock: the socket to emit nailgun protocol chunks over.
    :param tuple chunk_and_eof_types: A tuple of two ChunkType instances: the first for a buffer
      holding data, and the second for a chunk representing EOF. If the second ChunkType is None,
      EOF will not be treated specially.
    :param int buf_size: the buffer size for reads from the file descriptor.
    :param int select_timeout: the timeout (in seconds) for select.select() calls against the fd.
    """
    super(NailgunStreamWriter, self).__init__()
    self.daemon = True
    self._in_file = in_file
    self._socket = sock
    self._buf_size = buf_size or io.DEFAULT_BUFFER_SIZE
    self._chunk_type = chunk_type
    self._chunk_eof_type = chunk_eof_type
    self._select_timeout = select_timeout or self.SELECT_TIMEOUT
    # N.B. This Event is used as nothing more than a convenient atomic flag - nothing waits on it.
    self._stopped = threading.Event()

  @property
  def is_stopped(self):
    """Indicates whether or not the instance is stopped."""
    return self._stopped.is_set()

  def stop(self):
    """Stops the instance."""
    self._stopped.set()

  @classmethod
  @contextmanager
  def open(cls, sock, chunk_type, chunk_eof_type, isatty=False, buf_size=None, select_timeout=None):
    """Yields the write side of a pipe that will copy appropriately chunked values to the socket."""
    with _pipe(isatty) as (read_handle, write_handle):
      writer = NailgunStreamWriter(read_handle, sock, chunk_type, chunk_eof_type,
                                  buf_size=buf_size, select_timeout=select_timeout)
      with writer.running():
        yield write_handle

  @contextmanager
  def running(self):
    self.start()
    try:
      yield
    finally:
      self.stop()

  def run(self):
    while not self.is_stopped:
      readable, _, errored = select.select([self._in_file], [], [self._in_file], self._select_timeout)

      if self._in_file in errored:
        self.stop()
        return

      if not self.is_stopped and self._in_file in readable:
        data = os.read(self._in_file.fileno(), self._buf_size)

        if not self.is_stopped:
          if data:
            NailgunProtocol.write_chunk(self._socket, self._chunk_type, data)
          else:
            try:
              if self._chunk_eof_type is not None:
                NailgunProtocol.write_chunk(self._socket, self._chunk_eof_type)
                self._socket.shutdown(socket.SHUT_WR)  # Shutdown socket sends.
            except socket.error:  # Can happen if response is quick.
              pass
            finally:
              self.stop()
