# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import threading


class FileBackedRWBuf:
    """An unbounded read-write buffer backed by a file.

    Can be used as a file-like object for reading and writing the underlying file. Has a fileno, so
    you can redirect stdout/stderr of subprocess.Popen() etc. to this object. This is useful when
    you want to poll the output of long-running subprocesses in a separate thread.
    """

    def __init__(self, backing_file):
        self._lock = threading.Lock()
        self._io = open(backing_file, "a+b")
        self._readpos = 0
        self.fileno = self._io.fileno

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
            raise ValueError(f"Expected bytes, not {type(s)}, for argument {s}")
        with self._lock:
            self.do_write(s)
            self._io.flush()

    def flush(self):
        with self._lock:
            self._io.flush()

    def close(self):
        self._io.close()

    def do_write(self, s):
        self._io.write(s)
