# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import threading
from builtins import bytes, object, open, str
from io import BytesIO


class _RWBuf(object):
  """An unbounded read-write buffer.

  Can be used as a file-like object for reading and writing.
  Subclasses implement write functionality."""

  def __init__(self, io):
    self._lock = threading.Lock()
    self._io = io
    self._readpos = 0

  def read(self, size=-1):
    with self._lock:
      self._io.seek(self._readpos)
      ret = self._io.read() if size == -1 else self._io.read(size)
      self._readpos = self._io.tell()
      return ret

  def read_from(self, pos, size=-1):
    with self._lock:
      self._io.seek(pos)
      return self._io.read() if size == -1 else self._io.read(size)

  def write(self, s):
    if not isinstance(s, bytes):
      raise ValueError('Expected bytes, not {}, for argument {}'.format(type(s), s))
    with self._lock:
      self.do_write(s)
      self._io.flush()

  def flush(self):
    with self._lock:
      self._io.flush()

  def close(self):
    self._io.close()

  def do_write(self, s):
    raise NotImplementedError


class InMemoryRWBuf(_RWBuf):
  """An unbounded read-write buffer entirely in memory.

  Can be used as a file-like object for reading and writing. Note that it can't be used in
  situations that require a real file (e.g., redirecting stdout/stderr of subprocess.Popen())."""

  def __init__(self):
    super(InMemoryRWBuf, self).__init__(BytesIO())
    self._writepos = 0

  def do_write(self, s):
    self._io.seek(self._writepos)
    self._io.write(s)
    self._writepos = self._io.tell()


class FileBackedRWBuf(_RWBuf):
  """An unbounded read-write buffer backed by a file.

  Can be used as a file-like object for reading and writing the underlying file. Has a fileno,
  so you can redirect stdout/stderr of subprocess.Popen() etc. to this object. This is useful
  when you want to poll the output of long-running subprocesses in a separate thread."""

  def __init__(self, backing_file):
    _RWBuf.__init__(self, open(backing_file, 'a+b'))
    self.fileno = self._io.fileno

  def do_write(self, s):
    self._io.write(s)


class StringWriter(object):
  """A write-only buffer which accepts strings and writes to another buffer which accepts bytes.

  Writes strings as utf-8.

  This is write-only because it's unclear whether seeking should seek by code-point or byte, and
  implementing the former is non-trivial. If you need to read, read from the underlying buffer's
  bytes.
  """

  def __init__(self, underlying):
    """
    :param underlying: Any file-like object which has a write(binary_string) function.
    """
    # Called buffer to mirror how sys.stdout and sys.stderr expose this.
    self.buffer = underlying

  def write(self, s):
    if not isinstance(s, str):
      raise ValueError('Expected unicode str, not {}, for argument {}'.format(type(s), s))
    self.buffer.write(s.encode('utf-8'))

  def flush(self):
    self.buffer.flush()

  def close(self):
    self.buffer.close()
