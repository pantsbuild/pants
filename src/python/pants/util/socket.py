# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import select
import socket


class RecvBufferedSocket(object):
  """A socket wrapper that simplifies recv() buffering."""

  DEFAULT_CHUNK_BYTES = 8192

  def __init__(self, socket, chunk_size=DEFAULT_CHUNK_BYTES, select_timeout=None):
    """
    :param socket socket: The socket.socket object to wrap.
    :param int chunk_size: The smallest max read size for calls to recv() in bytes.
    :param float select_timeout: The select timeout for a socket read in seconds. An integer value
                                 effectively makes self.recv non-blocking (default: None, blocking).
    """
    self._chunk_size = chunk_size
    self._socket = socket
    self._buffer = b''
    self._select_timeout = select_timeout

  def recv(self, bufsize):
    """Buffers up to _chunk_size bytes when the internal buffer has less than `bufsize` bytes."""
    assert bufsize > 0, 'a positive bufsize is required'

    if len(self._buffer) < bufsize:
      readable, _, _ = select.select([self._socket], [], [], self._select_timeout)
      if readable:
        recvd = self._socket.recv(max(self._chunk_size, bufsize))
        self._buffer = self._buffer + recvd
    return_buf, self._buffer = self._buffer[:bufsize], self._buffer[bufsize:]
    return return_buf

  def __getattr__(self, attr):
    return getattr(self._socket, attr)
