# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import errno
import io
import select
import socket
from builtins import object


def teardown_socket(s):
  """Shuts down and closes a socket."""
  try:
    s.shutdown(socket.SHUT_WR)
  except socket.error:
    pass
  finally:
    s.close()


def safe_select(*args, **kwargs):
  # N.B. This while loop is purely to facilitate SA_RESTART-like behavior for select(), which is
  # (apparently) not covered by signal.siginterrupt(signal.SIGINT, False) when a timeout is passed.
  # This helps avoid an unhandled select.error(4, 'Interrupted system call') on SIGINT.
  # See https://bugs.python.org/issue12224 for more info.
  while 1:
    try:
      return select.select(*args, **kwargs)
    except (OSError, select.error) as e:
      if e[0] != errno.EINTR:
        raise


class RecvBufferedSocket(object):
  """A socket wrapper that simplifies recv() buffering."""

  def __init__(self, sock, chunk_size=io.DEFAULT_BUFFER_SIZE, select_timeout=None):
    """
    :param socket sock: The socket.socket object to wrap.
    :param int chunk_size: The smallest max read size for calls to recv() in bytes.
    :param float select_timeout: The select timeout for a socket read in seconds. An integer value
                                 effectively makes self.recv non-blocking (default: None, blocking).
    """
    self._socket = sock
    self._chunk_size = chunk_size
    self._select_timeout = select_timeout
    self._buffer = b''
    self._maybe_tune_socket(sock)

  def _maybe_tune_socket(self, sock):
    try:
      # Disable Nagle's algorithm to improve latency.
      sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (OSError, IOError):
      # This can fail in tests where `socket.socketpair()` is used, or potentially
      # in odd environments - but we shouldn't ever crash over it.
      return

  def recv(self, bufsize):
    """Buffers up to _chunk_size bytes when the internal buffer has less than `bufsize` bytes."""
    assert bufsize > 0, 'a positive bufsize is required'

    if len(self._buffer) < bufsize:
      readable, _, _ = safe_select([self._socket], [], [], self._select_timeout)
      if readable:
        recvd = self._socket.recv(max(self._chunk_size, bufsize))
        self._buffer = self._buffer + recvd
    return_buf, self._buffer = self._buffer[:bufsize], self._buffer[bufsize:]
    return return_buf

  def __getattr__(self, attr):
    return getattr(self._socket, attr)
