# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import errno
import io
import socket
from builtins import object

from future.utils import PY3


if PY3:
  import selectors
else:
  import select


def teardown_socket(s):
  """Shuts down and closes a socket."""
  try:
    s.shutdown(socket.SHUT_WR)
  except socket.error:
    pass
  finally:
    s.close()


# TODO(6071): Remove this once we drop Python 2, because 1) we no longer want to use select.select()
# in favor of https://docs.python.org/3/library/selectors.html, which uses more efficient and robust
# algorithms at a better level of abstraction, and because 2) PEP 474 fixed the issue with SIGINT
# https://www.python.org/dev/peps/pep-0475/.
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


# TODO(6071): require kwarg-only args after `fileobj`.
def is_readable(fileobj, timeout=None):
  """Check that the file-like resource is readable within the given timeout via polling.
  :param Union[int, SupportsFileNo] fileobj:
  :param Optional[int] timeout: (in seconds)
  :return bool
  """
  if PY3:
    with selectors.DefaultSelector() as selector:
      selector.register(fileobj, selectors.EVENT_READ)
      events = selector.select(timeout=timeout)
    return bool(events)
  else:
    readable, _, _ = safe_select([fileobj], [], [], timeout)
    return bool(readable)


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

    if len(self._buffer) < bufsize and is_readable(self._socket, timeout=self._select_timeout):
      recvd = self._socket.recv(max(self._chunk_size, bufsize))
      self._buffer = self._buffer + recvd
    return_buf, self._buffer = self._buffer[:bufsize], self._buffer[bufsize:]
    return return_buf

  def __getattr__(self, attr):
    return getattr(self._socket, attr)
