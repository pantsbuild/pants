# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import threading

from six import StringIO


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
    with self._lock:
      self.do_write(str(s))
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
    _RWBuf.__init__(self, StringIO())
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
    _RWBuf.__init__(self, open(backing_file, 'a+'))
    self.fileno = self._io.fileno

  def do_write(self, s):
    self._io.write(s)
