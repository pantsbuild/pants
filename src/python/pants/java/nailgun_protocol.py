# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import struct
from builtins import bytes, object, str, zip


STDIO_DESCRIPTORS = (0, 1, 2)


class ChunkType(object):
  """Nailgun protocol chunk types.

  N.B. Because we force `__future__.unicode_literals` in sources, string literals are automatically
  converted to unicode for us (e.g. 'xyz' automatically becomes u'xyz'). In the case of protocol
  implementations, supporting methods like struct.pack() require ASCII values - so we specify
  constants such as these as byte literals (e.g. b'xyz', which can only contain ASCII values)
  rather than their unicode counterparts. The alternative is to call str.encode('ascii') to
  convert the unicode string literals to ascii before use.
  """

  ARGUMENT = b'A'
  ENVIRONMENT = b'E'
  WORKING_DIR = b'D'
  COMMAND = b'C'
  PID = b'P'  # This is a custom extension to the Nailgun protocol spec for transmitting pid info.
  STDIN = b'0'
  STDOUT = b'1'
  STDERR = b'2'
  START_READING_INPUT = b'S'
  STDIN_EOF = b'.'
  EXIT = b'X'
  REQUEST_TYPES = (ARGUMENT, ENVIRONMENT, WORKING_DIR, COMMAND)
  EXECUTION_TYPES = (PID, STDIN, STDOUT, STDERR, START_READING_INPUT, STDIN_EOF, EXIT)
  VALID_TYPES = REQUEST_TYPES + EXECUTION_TYPES


class NailgunProtocol(object):
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

  ENVIRON_SEP = '='
  TTY_ENV_TMPL = 'NAILGUN_TTY_{}'
  TTY_PATH_ENV = 'NAILGUN_TTY_PATH_{}'
  HEADER_FMT = b'>Ic'
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
        yield item.decode('utf-8')
      else:
        yield item

  @classmethod
  def send_request(cls, sock, working_dir, command, *arguments, **environment):
    """Send the initial Nailgun request over the specified socket."""
    for argument in arguments:
      cls.write_chunk(sock, ChunkType.ARGUMENT, argument)

    for item_tuple in environment.items():
      cls.write_chunk(sock,
                      ChunkType.ENVIRONMENT,
                      cls.ENVIRON_SEP.join(cls._decode_unicode_seq(item_tuple)))

    cls.write_chunk(sock, ChunkType.WORKING_DIR, working_dir)
    cls.write_chunk(sock, ChunkType.COMMAND, command)

  @classmethod
  def parse_request(cls, sock):
    """Parse the request (the pre-execution) section of the nailgun protocol from the given socket.

    Handles reading of the Argument, Environment, Working Directory and Command chunks from the
    client which represents the "request" phase of the exchange. Working Directory and Command are
    required and must be sent as the last two chunks in this phase. Argument and Environment chunks
    are optional and can be sent more than once (thus we aggregate them).
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
        raise cls.ProtocolError('received non-request chunk before header was fully received!')

    return working_dir, command, arguments, environment

  @classmethod
  def write_chunk(cls, sock, chunk_type, payload=b''):
    """Write a single chunk to the connected client."""
    chunk = cls.construct_chunk(chunk_type, payload)
    sock.sendall(chunk)

  @classmethod
  def construct_chunk(cls, chunk_type, payload, encoding='utf-8'):
    """Construct and return a single chunk."""
    if isinstance(payload, str):
      payload = payload.encode(encoding)
    elif not isinstance(payload, bytes):
      raise TypeError('cannot encode type: {}'.format(type(payload)))

    header = struct.pack(cls.HEADER_FMT, len(payload), chunk_type)
    return header + payload

  @classmethod
  def _read_until(cls, sock, desired_size):
    """Read a certain amount of content from a socket before returning."""
    buf = b''
    while len(buf) < desired_size:
      recv_bytes = sock.recv(desired_size - len(buf))
      if not recv_bytes:
        raise cls.TruncatedRead('Expected {} bytes before socket shutdown, instead received {}'
                                .format(desired_size, len(buf)))
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
      raise cls.TruncatedHeaderError('Failed to read nailgun chunk header ({!r}).'.format(e))

    # Unpack the chunk header.
    payload_len, chunk_type = struct.unpack(cls.HEADER_FMT, header)

    try:
      # Read the chunk payload.
      payload = cls._read_until(sock, payload_len)
    except cls.TruncatedRead as e:
      raise cls.TruncatedPayloadError('Failed to read nailgun chunk payload ({!r}).'.format(e))

    # In the case we get an otherwise well-formed chunk, check the chunk_type for validity _after_
    # we've drained the payload from the socket to avoid subsequent reads of a stale payload.
    if chunk_type not in ChunkType.VALID_TYPES:
      raise cls.ProtocolError('invalid chunk type: {}'.format(chunk_type))
    if not return_bytes:
      payload = payload.decode('utf-8')

    return chunk_type, payload

  @classmethod
  def iter_chunks(cls, sock, return_bytes=False):
    """Generates chunks from a connected socket until an Exit chunk is sent."""
    while 1:
      chunk_type, payload = cls.read_chunk(sock, return_bytes)
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
  def send_exit(cls, sock, payload=b''):
    """Send the Exit chunk over the specified socket."""
    cls.write_chunk(sock, ChunkType.EXIT, payload)

  @classmethod
  def send_pid(cls, sock, pid):
    """Send the PID chunk over the specified socket."""
    cls.write_chunk(sock, ChunkType.PID, pid)

  @classmethod
  def encode_process_exit_code(cls, code):
    """???"""
    if not isinstance(code, int):
      raise Exception('???')
    return str(code).encode('ascii')

  @classmethod
  def send_exit_with_code(cls, sock, code):
    """???"""
    encoded_exit_status = cls.encode_process_exit_code(code)
    cls.send_exit(sock, payload=encoded_exit_status)

  @classmethod
  def encode_env_var_value(cls, obj):
    """???"""
    # return str(obj).encode('utf-8')
    return binary_type(str(obj))

  @classmethod
  def isatty_to_env(cls, stdin, stdout, stderr):
    """Generate nailgun tty capability environment variables based on checking a set of fds.

    :param file stdin: The stream to check for stdin tty capabilities.
    :param file stdout: The stream to check for stdout tty capabilities.
    :param file stderr: The stream to check for stderr tty capabilities.
    :returns: A dict containing the tty capability environment variables.
    """
    def gen_env_vars():
      for fd_id, fd in zip(STDIO_DESCRIPTORS, (stdin, stdout, stderr)):
        is_atty = fd.isatty()
        yield (cls.TTY_ENV_TMPL.format(fd_id), cls.encode_env_var_value(int(is_atty)))
        if is_atty:
          yield (cls.TTY_PATH_ENV.format(fd_id), os.ttyname(fd.fileno()) or b'')
    return dict(gen_env_vars())

  @classmethod
  def isatty_from_env(cls, env):
    """Determine whether remote file descriptors are tty capable using std nailgunned env variables.

    :param dict env: A dictionary representing the environment.
    :returns: A tuple of boolean values indicating istty or not for (stdin, stdout, stderr).
    """
    def str_int_bool(i):
      return i.isdigit() and bool(int(i))  # Environment variable values should always be strings.

    return tuple(
      str_int_bool(env.get(cls.TTY_ENV_TMPL.format(fd_id), '0')) for fd_id in STDIO_DESCRIPTORS
    )

  @classmethod
  def ttynames_from_env(cls, env):
    """Determines the ttynames for remote file descriptors (if ttys).

    :param dict env: A dictionary representing the environment.
    :returns: A tuple of boolean values indicating ttyname paths or None for (stdin, stdout, stderr).
    """
    return tuple(env.get(cls.TTY_PATH_ENV.format(fd_id)) for fd_id in STDIO_DESCRIPTORS)
