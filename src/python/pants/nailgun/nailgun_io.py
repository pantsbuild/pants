# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import io
import os
import select
import threading
from contextlib import contextmanager

from pants.nailgun.nailgun_protocol import NailgunProtocol


class _StoppableDaemonThread(threading.Thread):
    """A stoppable daemon threading.Thread."""

    JOIN_TIMEOUT = 3

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
        return super().join(timeout or self.JOIN_TIMEOUT)

    @contextmanager
    def running(self):
        self.start()
        try:
            yield
        finally:
            self.stop()
            self.join()


class NailgunStreamWriter(_StoppableDaemonThread):
    """Reads input from an input fd and writes Nailgun chunks on a socket.

    Should generally be managed with the `open` classmethod contextmanager, which will create a pipe
    and provide its writing end to the caller.
    """

    SELECT_TIMEOUT = 0.15

    def __init__(
        self, in_fds, sock, chunk_types, chunk_eof_type, buf_size=None, select_timeout=None
    ):
        """
        :param tuple in_fds: A tuple of input file descriptors to read from.
        :param socket sock: the socket to emit nailgun protocol chunks over.
        :param tuple chunk_types: A tuple of chunk types with a 1:1 positional association with in_files.
        :param int chunk_eof_type: The nailgun chunk type for EOF (applies only to stdin).
        :param int buf_size: the buffer size for reads from the file descriptor.
        :param int select_timeout: the timeout (in seconds) for select.select() calls against the fd.
        """
        super().__init__(name=self.__class__.__name__)
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
        assert len({len(i) for i in iterables}) == 1, "inputs are not aligned"

    def _handle_closed_input_stream(self, fileno):
        # We've reached EOF.
        try:
            if self._chunk_eof_type is not None:
                NailgunProtocol.write_chunk(self._socket, self._chunk_eof_type)
        finally:
            try:
                os.close(fileno)
            finally:
                self._stop_reading_from_fd(fileno)

    def _stop_reading_from_fd(self, fileno):
        """Stop reading from the given fd.

        May safely be called multiple times.
        """
        self._in_fds = [fd for fd in self._in_fds if fd != fileno]

    def run(self):
        while self._in_fds and not self.is_stopped:
            # NB: For now, we stick with select.select, rather than the better abstracted and more robust
            # selectors.DefaultSelector. We do this because we currently check for errored_fds, and this
            # cannot be easily recreated with selectors (https://stackoverflow.com/a/49563017). See
            # https://github.com/pantsbuild/pants/issues/7880 for why we might want to revisit this code
            # to instead use selectors.
            readable_fds, _, errored_fds = select.select(
                self._in_fds, [], self._in_fds, self._select_timeout
            )
            self.do_run(readable_fds, errored_fds)

    def do_run(self, readable_fds, errored_fds):
        """Represents one iteration of the infinite reading cycle."""
        if readable_fds:
            for fileno in readable_fds:
                data = os.read(fileno, self._buf_size)
                if not data:
                    self._handle_closed_input_stream(fileno)
                else:
                    NailgunProtocol.write_chunk(
                        self._socket, self._fileno_chunk_type_map[fileno], data
                    )

        if errored_fds:
            for fileno in errored_fds:
                self._stop_reading_from_fd(fileno)
