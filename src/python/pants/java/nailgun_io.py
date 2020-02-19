# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import io
import os
import select
import threading
from contextlib import contextmanager

from contextlib2 import ExitStack

from pants.java.nailgun_protocol import ChunkType, NailgunProtocol


class Pipe:
    """Wrapper around OS pipes, that knows whether its write end is closed.

    Note that this exposes raw file descriptors,
    which means that we could plausibly close one of the ends and re-open it with a different file,
    before this class notices. For this reason, it is advised to be very careful with these
    file descriptors.

    TODO Wrap the read and write operations, so that we don't have to expose raw fds anymore.
    This is not possible yet, because stdio_as needs to replace the fds at the OS level.
    """

    def __init__(self, read_fd, write_fd):
        self.read_fd = read_fd
        self.write_fd = write_fd
        # TODO Declare as a datatype when #6374 is merged or we have moved to dataclasses.
        self.writable = True

    def is_writable(self):
        """If the write end of a pipe closes, the read end might still be open, to allow readers to
        finish reading before closing it. However, there are cases where we still want to know if
        the write end is closed.

        :return: True if the write end of the pipe is open.
        """
        if not self.writable:
            return False

        try:
            os.fstat(self.write_fd)
        except OSError:
            return False
        return True

    def stop_writing(self):
        """Mark that you wish to close the write end of this pipe."""
        self.writable = False

    def close(self):
        """Close the reading end of the pipe, which should close the writing end too."""
        os.close(self.read_fd)
        self.writable = False

    @staticmethod
    def create(isatty):
        """Open a pipe and create wrapper object."""
        read_fd, write_fd = os.openpty() if isatty else os.pipe()
        return Pipe(read_fd, write_fd)

    @staticmethod
    @contextmanager
    def self_closing(isatty):
        """Create a pipe and close it when done."""
        pipe = Pipe.create(isatty)
        try:
            yield pipe
        finally:
            pipe.close()


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

    def __init__(self, maybe_shutdown_socket, write_handle):
        """
        :param socket sock: the socket to read nailgun protocol chunks from.
        :param file write_handle: A file-like (usually the write end of a pipe/pty) onto which
          to write data decoded from the chunks.
        """
        super().__init__(name=self.__class__.__name__)
        self._maybe_shutdown_socket = maybe_shutdown_socket
        self._write_handle = write_handle

    @classmethod
    @contextmanager
    def open(cls, maybe_shutdown_socket, isatty=False):
        # We use a plain pipe here (as opposed to a self-closing pipe), because
        # NailgunStreamStdinReader will close the file descriptor it's writing to when it's done.
        # Therefore, when _self_closing_pipe tries to clean up, it will try to close an already closed fd.
        # The alternative is passing an os.dup(write_fd) to NSSR, but then we have the problem where
        # _self_closing_pipe doens't close the write_fd until the pants run is done, and that generates
        # issues around piping stdin to interactive processes such as REPLs.
        pipe = Pipe.create(isatty)
        reader = NailgunStreamStdinReader(maybe_shutdown_socket, os.fdopen(pipe.write_fd, "wb"))
        with reader.running():
            # Instruct the thin client to begin reading and sending stdin.
            with maybe_shutdown_socket.lock:
                NailgunProtocol.send_start_reading_input(maybe_shutdown_socket.socket)
            try:
                yield pipe.read_fd
            finally:
                pipe.close()

    def run(self):
        try:
            for chunk_type, payload in NailgunProtocol.iter_chunks(
                self._maybe_shutdown_socket, return_bytes=True
            ):
                if self.is_stopped:
                    return

                if chunk_type == ChunkType.STDIN:
                    self._write_handle.write(payload)
                    self._write_handle.flush()
                elif chunk_type == ChunkType.STDIN_EOF:
                    return
                else:
                    raise NailgunProtocol.ProtocolError(
                        "received unexpected chunk {} -> {}".format(chunk_type, payload)
                    )
        finally:
            try:
                self._write_handle.close()
            except (OSError, IOError):
                pass


class NailgunStreamWriterError(Exception):
    pass


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
                self.stop_reading_from_fd(fileno)

    def stop_reading_from_fd(self, fileno):
        self._in_fds.remove(fileno)

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
        """Represents one iteration of the infinite reading cycle.

        Subclasses should override this.
        """
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
                self.stop_reading_from_fd(fileno)


class PipedNailgunStreamWriter(NailgunStreamWriter):
    """Represents a NailgunStreamWriter that reads from a pipe."""

    def __init__(self, pipes, socket, chunk_type, *args, **kwargs):
        self._pipes = pipes
        in_fds = tuple(pipe.read_fd for pipe in pipes)
        super().__init__(in_fds, socket, chunk_type, *args, **kwargs)

    def do_run(self, readable_fds, errored_fds):
        """Overrides the superclass.

        Wraps the running logic of the parent class to handle pipes that have been closed on the
        write end. If no file descriptors are readable (i.e. there is no more to read from any pipe
        for now), it will check each of its pipes. If a pipe is not writable, it will interpret that
        the writer class does not want to write any more, and so it will remove that pipe from the
        available pipes to read from. When there are no more pipes to read from, it will stop.
        """
        if not readable_fds:
            for pipe in self._pipes:
                if not pipe.is_writable():
                    self.stop_reading_from_fd(pipe.read_fd)
                    self._pipes.remove(pipe)
        if not self._pipes:
            self.stop()
        super().do_run(readable_fds, errored_fds)

    @classmethod
    @contextmanager
    def open(
        cls, sock, chunk_type, isatty, chunk_eof_type=None, buf_size=None, select_timeout=None
    ):
        """Yields the write side of a pipe that will copy appropriately chunked values to a
        socket."""
        with cls.open_multi(
            sock, (chunk_type,), (isatty,), chunk_eof_type, buf_size, select_timeout
        ) as ctx:
            yield ctx

    @classmethod
    @contextmanager
    def open_multi(
        cls, sock, chunk_types, isattys, chunk_eof_type=None, buf_size=None, select_timeout=None
    ):
        """Yields the write sides of pipes that will copy appropriately chunked values to the
        socket."""
        cls._assert_aligned(chunk_types, isattys)

        # N.B. This is purely to permit safe handling of a dynamic number of contextmanagers.
        with ExitStack() as stack:
            pipes = list(
                # Allocate one pipe pair per chunk type provided.
                (stack.enter_context(Pipe.self_closing(isatty)) for isatty in isattys)
            )
            writer = PipedNailgunStreamWriter(
                pipes,
                sock,
                chunk_types,
                chunk_eof_type,
                buf_size=buf_size,
                select_timeout=select_timeout,
            )
            with writer.running():
                yield pipes, writer
