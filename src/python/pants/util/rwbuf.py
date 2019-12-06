# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import subprocess
import threading
from io import BytesIO


logger = logging.getLogger(__name__)


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

  def do_flush(self):
    self._io.flush()

  def write(self, s):
    if not isinstance(s, bytes):
      raise ValueError('Expected bytes, not {}, for argument {}'.format(type(s), s))
    with self._lock:
      self.do_write(s)
      self.do_flush()

  def flush(self):
    with self._lock:
      self.do_flush()

  def close(self):
    self._io.close()

  def do_write(self, s):
    raise NotImplementedError


class InMemoryRWBuf(_RWBuf):
  """An unbounded read-write buffer entirely in memory.

  Can be used as a file-like object for reading and writing. Note that it can't be used in
  situations that require a real file (e.g., redirecting stdout/stderr of subprocess.Popen())."""

  def __init__(self):
    super().__init__(BytesIO())
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


class OutputTeeingFileBackedRWBuf(_RWBuf):
  """A read-write buffer that invokes 'tee' to spread output across multiple files, or stdout.

  This buffer can be used in situations that require a real file, as it provides the file descriptor
  of the underlying 'tee' process's stdin in `self.fileno`.
  """

  def __init__(self, backing_file, files_to_tee_to):
    inherit_stdout = False

    real_file_outputs = []
    for f in files_to_tee_to:
      if f == '/dev/stdout':
        logger.debug(f'inheriting stdout for the output meant for {backing_file}')
        inherit_stdout = True
        continue
      real_file_outputs.append(f)

    logger.debug(f'opening backing file {backing_file}, teeing to {real_file_outputs}, inherit_stdout: {inherit_stdout}')
    self.backing_tee_process = subprocess.Popen(
      args=['tee', '-a', backing_file, *real_file_outputs],
      stdin=subprocess.PIPE,
      stdout=(None if inherit_stdout else subprocess.DEVNULL),
      # Don't inherit stderr, and if we do inherit stdout, just send stderr to that as well.
      stderr=subprocess.STDOUT,
    )
    super().__init__(self.backing_tee_process.stdin)

    # Make the tee process the input for any subprocesses.
    self.fileno = self.backing_tee_process.stdin.fileno

    # Use a handle on the real file for reading any output.
    self.real_file = open(backing_file, 'a+b')

  def read(self, size=-1):
    with self._lock:
      self.real_file.seek(self._readpos)
      ret = self.real_file.read() if size == -1 else self.real_file.read(size)
      self._readpos = self.real_file.tell()
      return ret

  def read_from(self, pos, size=-1):
    with self._lock:
      self.real_file.seek(pos)
      return self.real_file.read() if size == -1 else self.real_file.read(size)

  def close(self):
    # This should close the 'tee' process's stdin, which should cause it to quickly exit.
    super().close()
    rc = self.backing_tee_process.wait()
    if rc != 0:
      raise ValueError('backing tee process {self.backing_tee_process} exited with code {rc}!')
    # Also close the handle to the real file!
    self.real_file.close()

  def do_write(self, s):
    # This writes to the 'tee' process.
    self._io.write(s)


class StringWriter:
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
    self.buffer.write(s.encode())

  def flush(self):
    self.buffer.flush()

  def close(self):
    self.buffer.close()
