# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import io
import os
import select
import socket
import threading
from contextlib import contextmanager

from pants.java.nailgun_protocol import ChunkType, NailgunProtocol


class NailgunStreamReader(threading.Thread):
  """Reads input from stdin and emits Nailgun 'stdin' chunks over a socket."""

  SELECT_TIMEOUT = 1

  def __init__(self, in_fd, sock, buf_size=io.DEFAULT_BUFFER_SIZE, select_timeout=SELECT_TIMEOUT):
    """
    :param file in_fd: the input file descriptor (e.g. sys.stdin) to read from.
    :param socket sock: the socket to emit nailgun protocol chunks over.
    :param int buf_size: the buffer size for reads from the file descriptor.
    :param int select_timeout: the timeout (in seconds) for select.select() calls against the fd.
    """
    super(NailgunStreamReader, self).__init__()
    self.daemon = True
    self._stdin = in_fd
    self._socket = sock
    self._buf_size = buf_size
    self._select_timeout = select_timeout
    # N.B. This Event is used as nothing more than a convenient atomic flag - nothing waits on it.
    self._stopped = threading.Event()

  @property
  def is_stopped(self):
    """Indicates whether or not the instance is stopped."""
    return self._stopped.is_set()

  def stop(self):
    """Stops the instance."""
    self._stopped.set()

  @contextmanager
  def running(self):
    self.start()
    yield
    self.stop()

  def run(self):
    while not self.is_stopped:
      readable, _, errored = select.select([self._stdin], [], [self._stdin], self._select_timeout)

      if self._stdin in errored:
        self.stop()
        return

      if not self.is_stopped and self._stdin in readable:
        data = os.read(self._stdin.fileno(), self._buf_size)

        if not self.is_stopped:
          if data:
            NailgunProtocol.write_chunk(self._socket, ChunkType.STDIN, data)
          else:
            NailgunProtocol.write_chunk(self._socket, ChunkType.STDIN_EOF)
            try:
              self._socket.shutdown(socket.SHUT_WR)  # Shutdown socket sends.
            except socket.error:  # Can happen if response is quick.
              pass
            finally:
              self.stop()


class NailgunStreamWriter(object):
  """A sys.{stdout,stderr} replacement that writes output to a socket using the nailgun protocol."""

  def __init__(self, sock, chunk_type, isatty=True, mask_broken_pipe=False):
    """
    :param socket sock: A connected socket capable of speaking the nailgun protocol.
    :param str chunk_type: A ChunkType constant representing the nailgun protocol chunk type.
    :param bool isatty: Whether or not the consumer of this stream has tty capabilities. (Optional)
    :param bool mask_broken_pipe: This will toggle the masking of 'broken pipe' errors when writing
                                  to the remote socket. This allows for completion of execution in
                                  the event of a client disconnect (e.g. to support cleanup work).
    """
    self._socket = sock
    self._chunk_type = chunk_type
    self._isatty = isatty
    self._mask_broken_pipe = mask_broken_pipe

  def write(self, payload):
    try:
      NailgunProtocol.write_chunk(self._socket, self._chunk_type, payload)
    except IOError as e:
      # If the remote client disconnects and we try to perform a write (e.g. socket.send/sendall),
      # an 'error: [Errno 32] Broken pipe' exception can be thrown. Setting mask_broken_pipe=True
      # safeguards against this case (which is unexpected for most writers of sys.stdout etc) so
      # that we don't awkwardly interrupt the runtime by throwing this exception on writes to
      # stdout/stderr.
      if e.errno == errno.EPIPE and not self._mask_broken_pipe:
        raise

  def flush(self):
    return

  def isatty(self):
    return self._isatty
