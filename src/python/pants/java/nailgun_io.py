# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import io
import os
import select
import threading
from contextlib import contextmanager

from contextlib2 import ExitStack

from pants.java.nailgun_protocol import ChunkType, NailgunProtocol


@contextmanager
def _pipe(isatty):
  r_fd, w_fd = os.openpty() if isatty else os.pipe()
  try:
    yield (r_fd, w_fd)
  finally:
    os.close(r_fd)
    os.close(w_fd)


class _StoppableDaemonThread(threading.Thread):
  """A stoppable daemon threading.Thread."""

  JOIN_TIMEOUT = 3

  def __init__(self, *args, **kwargs):
    super(_StoppableDaemonThread, self).__init__(*args, **kwargs)
    self.daemon = True
    # N.B. This Event is used as nothing more than a convenient atomic flag - nothing waits on it.
    self._stopped = threading.Event()

  @property
  def is_stopped(self):
    """Indicates whether or not the instance is stopped."""
    return self._stopped.is_set()

  def stop(self):
    """Stops the instance."""
    self._stopped.set()

  def join(self, timeout=None):
    """Joins with a default timeout exposed on the class."""
    return super(_StoppableDaemonThread, self).join(timeout or self.JOIN_TIMEOUT)

  @contextmanager
  def running(self):
    self.start()
    try:
      yield
    finally:
      self.stop()
      self.join()


class NailgunStreamStdinReader(_StoppableDaemonThread):
  """Reads Nailgun 'stdin' chunks on a socket and writes them to an output file-like.

  Because a Nailgun server only ever receives STDIN and STDIN_EOF ChunkTypes after initial
  setup, this thread executes all reading from a server socket.

  Runs until the socket is closed.
  """

  def __init__(self, sock, write_handle):
    """
    :param socket sock: the socket to read nailgun protocol chunks from.
    :param file write_handle: A file-like (usually the write end of a pipe/pty) onto which
      to write data decoded from the chunks.
    """
    super(NailgunStreamStdinReader, self).__init__(name=self.__class__.__name__)
    self._socket = sock
    self._write_handle = write_handle

  @classmethod
  @contextmanager
  def open(cls, sock, isatty=False):
    with _pipe(isatty) as (read_fd, write_fd):
      reader = NailgunStreamStdinReader(sock, os.fdopen(write_fd, 'wb'))
      with reader.running():
        # Instruct the thin client to begin reading and sending stdin.
        NailgunProtocol.send_start_reading_input(sock)
        yield read_fd

  def run(self):
    try:
      for chunk_type, payload in NailgunProtocol.iter_chunks(self._socket, return_bytes=True):
        if self.is_stopped:
          return

        if chunk_type == ChunkType.STDIN:
          self._write_handle.write(payload)
          self._write_handle.flush()
        elif chunk_type == ChunkType.STDIN_EOF:
          return
        else:
          raise NailgunProtocol.ProtocolError(
            'received unexpected chunk {} -> {}'.format(chunk_type, payload)
          )
    finally:
      self._write_handle.close()


class NailgunStreamWriter(_StoppableDaemonThread):
  """Reads input from an input fd and writes Nailgun chunks on a socket.

  Should generally be managed with the `open` classmethod contextmanager, which will create
  a pipe and provide its writing end to the caller.
  """

  SELECT_TIMEOUT = .15

  def __init__(self, in_fds, sock, chunk_types, chunk_eof_type, buf_size=None, select_timeout=None):
    """
    :param tuple in_fds: A tuple of input file descriptors to read from.
    :param socket sock: the socket to emit nailgun protocol chunks over.
    :param tuple chunk_types: A tuple of chunk types with a 1:1 positional association with in_files.
    :param int chunk_eof_type: The nailgun chunk type for EOF (applies only to stdin).
    :param int buf_size: the buffer size for reads from the file descriptor.
    :param int select_timeout: the timeout (in seconds) for select.select() calls against the fd.
    """
    super(NailgunStreamWriter, self).__init__(name=self.__class__.__name__)
    # Validates that we've received file descriptor numbers.
    self._in_fds = [int(f) for f in in_fds]
    self._socket = sock
    self._chunk_eof_type = chunk_eof_type
    self._buf_size = buf_size or io.DEFAULT_BUFFER_SIZE
    self._select_timeout = select_timeout or self.SELECT_TIMEOUT
    self._assert_aligned(in_fds, chunk_types)
    self._fileno_chunk_type_map = {f: t for f, t in zip(in_fds, chunk_types)}

  @classmethod
  def _assert_aligned(self, *iterables):
    assert len(set(len(i) for i in iterables)) == 1, 'inputs are not aligned'

  @classmethod
  @contextmanager
  def open(cls, sock, chunk_type, isatty, chunk_eof_type=None, buf_size=None, select_timeout=None):
    """Yields the write side of a pipe that will copy appropriately chunked values to a socket."""
    with cls.open_multi(sock,
                        (chunk_type,),
                        (isatty,),
                        chunk_eof_type,
                        buf_size,
                        select_timeout) as ctx:
      yield ctx

  @classmethod
  @contextmanager
  def open_multi(cls, sock, chunk_types, isattys, chunk_eof_type=None, buf_size=None,
                 select_timeout=None):
    """Yields the write sides of pipes that will copy appropriately chunked values to the socket."""
    cls._assert_aligned(chunk_types, isattys)

    # N.B. This is purely to permit safe handling of a dynamic number of contextmanagers.
    with ExitStack() as stack:
      read_fds, write_fds = zip(
        # Allocate one pipe pair per chunk type provided.
        *(stack.enter_context(_pipe(isatty)) for isatty in isattys)
      )
      writer = NailgunStreamWriter(
        read_fds,
        sock,
        chunk_types,
        chunk_eof_type,
        buf_size=buf_size,
        select_timeout=select_timeout
      )
      with writer.running():
        yield write_fds, writer

  def run(self):
    while self._in_fds and not self.is_stopped:
      readable, _, errored = select.select(self._in_fds, [], self._in_fds, self._select_timeout)

      if readable:
        for fileno in readable:
          data = os.read(fileno, self._buf_size)

          if not data:
            # We've reached EOF.
            try:
              if self._chunk_eof_type is not None:
                NailgunProtocol.write_chunk(self._socket, self._chunk_eof_type)
            finally:
              try:
                os.close(fileno)
              finally:
                self._in_fds.remove(fileno)
          else:
            NailgunProtocol.write_chunk(
              self._socket,
              self._fileno_chunk_type_map[fileno],
              data
            )

      if errored:
        for fileno in errored:
          self._in_fds.remove(fileno)
