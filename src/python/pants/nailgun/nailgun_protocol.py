# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import datetime
import os
import socket
import struct
import threading
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass

STDIO_DESCRIPTORS = (0, 1, 2)


class ChunkType:
    """Nailgun protocol chunk types.

    N.B. Because we force `__future__.unicode_literals` in sources, string literals are automatically
    converted to unicode for us (e.g. 'xyz' automatically becomes u'xyz'). In the case of protocol
    implementations, supporting methods like struct.pack() require ASCII values - so we specify
    constants such as these as byte literals (e.g. b'xyz', which can only contain ASCII values)
    rather than their unicode counterparts. The alternative is to call str.encode('ascii') to
    convert the unicode string literals to ascii before use.
    """

    ARGUMENT = b"A"
    ENVIRONMENT = b"E"
    WORKING_DIR = b"D"
    COMMAND = b"C"
    STDIN = b"0"
    STDOUT = b"1"
    STDERR = b"2"
    START_READING_INPUT = b"S"
    STDIN_EOF = b"."
    EXIT = b"X"
    REQUEST_TYPES = (ARGUMENT, ENVIRONMENT, WORKING_DIR, COMMAND)
    EXECUTION_TYPES = (STDIN, STDOUT, STDERR, START_READING_INPUT, STDIN_EOF, EXIT)
    VALID_TYPES = REQUEST_TYPES + EXECUTION_TYPES


class NailgunProtocol:
    """A mixin that provides a base implementation of the Nailgun protocol as described on
    http://martiansoftware.com/nailgun/protocol.html.

    Communications proceed as follows:

      1) Client connects to server
      2) Client transmits zero or more "Argument" chunks
      3) Client transmits zero or more "Environment" chunks
      4) Client transmits exactly one "Working Directory" chunk
      5) Client transmits exactly one "Command" chunk
      6) If server requires stdin input, server transmits exactly one "Start-reading-input" chunk

      After step 5 (and/or 6) the following may happen, interleaved and in any order:

      7) Client transmits zero or more "stdin" chunks (Only if the client has received a
         "Start-reading-input" chunk, and only until the client transmits a "stdin-eof" chunk).
      8) Server transmits zero or more "stdout" chunks.
      9) Server transmits zero or more "stderr" chunks.

      Steps 7-9 repeat indefinitely until the server transmits an "exit" chunk.
    """

    ENVIRON_SEP = "="
    TTY_PATH_ENV = "NAILGUN_TTY_PATH_{}"
    HEADER_FMT = b">Ic"
    HEADER_BYTES = 5

    class ProtocolError(Exception):
        """Raised if there is an error in the underlying nailgun protocol."""

    class TruncatedRead(ProtocolError):
        """Raised if there is a socket error while reading an expected number of bytes."""

    class TruncatedHeaderError(TruncatedRead):
        """Raised if there is a socket error while reading the header bytes."""

    class TruncatedPayloadError(TruncatedRead):
        """Raised if there is a socket error while reading the payload bytes."""

    @classmethod
    def _decode_unicode_seq(cls, seq):
        for item in seq:
            if isinstance(item, bytes):
                yield item.decode()
            else:
                yield item

    @classmethod
    def send_request(cls, sock, working_dir, command, *arguments, **environment):
        """Send the initial Nailgun request over the specified socket."""
        for argument in arguments:
            cls.write_chunk(sock, ChunkType.ARGUMENT, argument)

        for item_tuple in environment.items():
            cls.write_chunk(
                sock,
                ChunkType.ENVIRONMENT,
                cls.ENVIRON_SEP.join(cls._decode_unicode_seq(item_tuple)),
            )

        cls.write_chunk(sock, ChunkType.WORKING_DIR, working_dir)
        cls.write_chunk(sock, ChunkType.COMMAND, command)

    @classmethod
    def parse_request(cls, sock):
        """Parse the request (the pre-execution) section of the nailgun protocol from the given
        socket.

        Handles reading of the Argument, Environment, Working Directory and Command chunks from the
        client which represents the "request" phase of the exchange. Working Directory and Command
        are required and must be sent as the last two chunks in this phase. Argument and Environment
        chunks are optional and can be sent more than once (thus we aggregate them).
        """

        command = None
        working_dir = None
        arguments = []
        environment = {}

        while not all((working_dir, command)):
            chunk_type, payload = cls.read_chunk(sock)

            if chunk_type == ChunkType.ARGUMENT:
                arguments.append(payload)
            elif chunk_type == ChunkType.ENVIRONMENT:
                key, val = payload.split(cls.ENVIRON_SEP, 1)
                environment[key] = val
            elif chunk_type == ChunkType.WORKING_DIR:
                working_dir = payload
            elif chunk_type == ChunkType.COMMAND:
                command = payload
            else:
                raise cls.ProtocolError(
                    "received non-request chunk before header was fully received!"
                )

        return working_dir, command, arguments, environment

    @classmethod
    def write_chunk(cls, sock, chunk_type, payload=b""):
        """Write a single chunk to the connected client."""
        chunk = cls.construct_chunk(chunk_type, payload)
        sock.sendall(chunk)

    @classmethod
    def construct_chunk(cls, chunk_type, payload, encoding="utf-8"):
        """Construct and return a single chunk."""
        if isinstance(payload, str):
            payload = payload.encode(encoding)
        elif not isinstance(payload, bytes):
            raise TypeError("cannot encode type: {}".format(type(payload)))

        header = struct.pack(cls.HEADER_FMT, len(payload), chunk_type)
        return header + payload

    @classmethod
    def _read_until(cls, sock, desired_size):
        """Read a certain amount of content from a socket before returning."""
        buf = b""
        while len(buf) < desired_size:
            recv_bytes = sock.recv(desired_size - len(buf))
            if not recv_bytes:
                raise cls.TruncatedRead(
                    "Expected {} bytes before socket shutdown, instead received {}".format(
                        desired_size, len(buf)
                    )
                )
            buf += recv_bytes
        return buf

    @classmethod
    def read_chunk(cls, sock, return_bytes=False):
        """Read a single chunk from the connected client.

        A "chunk" is a variable-length block of data beginning with a 5-byte chunk header and followed
        by an optional payload. The chunk header consists of:

             1) The length of the chunk's payload (not including the header) as a four-byte big-endian
                unsigned long. The high-order byte is header[0] and the low-order byte is header[3].

             2) A single byte identifying the type of chunk.
        """
        try:
            # Read the chunk header from the socket.
            header = cls._read_until(sock, cls.HEADER_BYTES)
        except cls.TruncatedRead as e:
            raise cls.TruncatedHeaderError("Failed to read nailgun chunk header ({!r}).".format(e))

        # Unpack the chunk header.
        payload_len, chunk_type = struct.unpack(cls.HEADER_FMT, header)

        try:
            # Read the chunk payload.
            payload = cls._read_until(sock, payload_len)
        except cls.TruncatedRead as e:
            raise cls.TruncatedPayloadError(
                "Failed to read nailgun chunk payload ({!r}).".format(e)
            )

        # In the case we get an otherwise well-formed chunk, check the chunk_type for validity _after_
        # we've drained the payload from the socket to avoid subsequent reads of a stale payload.
        if chunk_type not in ChunkType.VALID_TYPES:
            raise cls.ProtocolError("invalid chunk type: {}".format(chunk_type))
        if not return_bytes:
            payload = payload.decode()

        return chunk_type, payload

    class ProcessStreamTimeout(Exception):
        """Raised after a timeout completes when a timeout is set on the stream during iteration."""

    @classmethod
    @contextmanager
    def _set_socket_timeout(cls, sock, timeout=None):
        """Temporarily set a socket timeout in order to respect a timeout provided to.

        .iter_chunks().
        """
        if timeout is not None:
            prev_timeout = sock.gettimeout()
        try:
            if timeout is not None:
                sock.settimeout(timeout)
            yield
        except socket.timeout:
            raise cls.ProcessStreamTimeout("socket read timed out with timeout {}".format(timeout))
        finally:
            if timeout is not None:
                sock.settimeout(prev_timeout)

    @dataclass(frozen=True)
    class TimeoutOptions:
        start_time: float
        interval: float

    class TimeoutProvider(ABC):
        @abstractmethod
        def maybe_timeout_options(self):
            """Called on every stream iteration to obtain a possible specification for a timeout.

            If this method returns non-None, it should return an instance of `cls.TimeoutOptions`, which
            then initiates a timeout after which the stream will raise `cls.ProcessStreamTimeout`.

            :rtype: :class:`cls.TimeoutOptions`, or None
            """

    @classmethod
    def iter_chunks(cls, maybe_shutdown_socket, return_bytes=False, timeout_object=None):
        """Generates chunks from a connected socket until an Exit chunk is sent or a timeout occurs.

        :param sock: the socket to read from.
        :param bool return_bytes: If False, decode the payload into a utf-8 string.
        :param cls.TimeoutProvider timeout_object: If provided, will be checked every iteration for a
                                                   possible timeout.
        :raises: :class:`cls.ProcessStreamTimeout`
        """
        assert timeout_object is None or isinstance(timeout_object, cls.TimeoutProvider)

        if timeout_object is None:
            deadline = None
        else:
            options = timeout_object.maybe_timeout_options()
            if options is None:
                deadline = None
            else:
                deadline = options.start_time + options.interval

        while 1:
            if deadline is not None:
                overtime_seconds = deadline - time.time()
                if overtime_seconds > 0:
                    original_timestamp = datetime.datetime.fromtimestamp(deadline).isoformat()
                    raise cls.ProcessStreamTimeout(
                        "iterating over bytes from nailgun timed out at {}, overtime seconds: {}".format(
                            original_timestamp, overtime_seconds
                        )
                    )

            with maybe_shutdown_socket.lock:
                if maybe_shutdown_socket.is_shutdown:
                    break
                # We poll with low timeouts because we poll under a lock. This allows the DaemonPantsRunner
                # to shut down the socket, and us to notice, pretty quickly.
                with cls._set_socket_timeout(maybe_shutdown_socket.socket, timeout=0.01):
                    try:
                        chunk_type, payload = cls.read_chunk(
                            maybe_shutdown_socket.socket, return_bytes
                        )
                    except socket.timeout:
                        # Timeouts are handled by the surrounding loop
                        continue
            yield chunk_type, payload
            if chunk_type == ChunkType.EXIT:
                break

    @classmethod
    def send_start_reading_input(cls, sock):
        """Send the Start-Reading-Input chunk over the specified socket."""
        cls.write_chunk(sock, ChunkType.START_READING_INPUT)

    @classmethod
    def send_stdout(cls, sock, payload):
        """Send the Stdout chunk over the specified socket."""
        cls.write_chunk(sock, ChunkType.STDOUT, payload)

    @classmethod
    def send_stderr(cls, sock, payload):
        """Send the Stderr chunk over the specified socket."""
        cls.write_chunk(sock, ChunkType.STDERR, payload)

    @classmethod
    def send_exit(cls, sock, payload=b""):
        """Send the Exit chunk over the specified socket."""
        cls.write_chunk(sock, ChunkType.EXIT, payload)

    @classmethod
    def send_exit_with_code(cls, sock, code):
        """Send an Exit chunk over the specified socket, containing the specified return code."""
        encoded_exit_status = cls.encode_int(code)
        cls.send_exit(sock, payload=encoded_exit_status)

    @classmethod
    def encode_int(cls, obj):
        """Verify the object is an int, and ASCII-encode it.

        :param int obj: An integer to be encoded.
        :raises: :class:`TypeError` if `obj` is not an integer.
        :return: A binary representation of the int `obj` suitable to pass as the `payload` to
                 send_exit().
        """
        if not isinstance(obj, int):
            raise TypeError(
                "cannot encode non-integer object in encode_int(): object was {} (type '{}').".format(
                    obj, type(obj)
                )
            )
        return str(obj).encode("ascii")

    @classmethod
    def encode_env_var_value(cls, obj):
        """Convert `obj` into a UTF-8 encoded binary string.

        The result of this method be used as the value of an environment variable in a subsequent
        NailgunClient execution.
        """
        return str(obj).encode()

    @classmethod
    def ttynames_to_env(cls, stdin, stdout, stderr):
        """Generate nailgun tty capability environment variables based on checking a set of fds.

        :param file stdin: The stream to check for stdin tty capabilities.
        :param file stdout: The stream to check for stdout tty capabilities.
        :param file stderr: The stream to check for stderr tty capabilities.
        :returns: A dict containing the tty capability environment variables.
        """

        def gen_env_vars():
            for fd_id, fd in zip(STDIO_DESCRIPTORS, (stdin, stdout, stderr)):
                if fd.isatty():
                    yield (cls.TTY_PATH_ENV.format(fd_id), os.ttyname(fd.fileno()) or b"")

        return dict(gen_env_vars())

    @classmethod
    def ttynames_from_env(cls, env):
        """Determines the ttynames for remote file descriptors (if ttys).

        :param dict env: A dictionary representing the environment.
        :returns: A tuple of boolean values indicating ttyname paths or None for (stdin, stdout, stderr).
        """
        return tuple(env.get(cls.TTY_PATH_ENV.format(fd_id)) for fd_id in STDIO_DESCRIPTORS)


class MaybeShutdownSocket:
    """A wrapper around a socket which knows whether it has been shut down.

    Because we may shut down a nailgun socket from one thread, and read from it on another, we use
    this wrapper so that a shutting-down thread can signal to a reading thread that it should stop
    reading.

    lock guards access to is_shutdown, shutting down the socket, and any calls which need to guarantee
    they don't race a shutdown call.
    """

    def __init__(self, sock):
        self.socket = sock
        self.lock = threading.Lock()
        self.is_shutdown = False
