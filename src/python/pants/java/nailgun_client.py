# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import select
import socket
import struct
import sys
import threading
from functools import partial


class NailgunSession(object):
  """Handles a single nailgun command session."""

  class ProtocolError(Exception):
    """Thrown if there is an error in the underlying nailgun protocol."""

  # See: http://www.martiansoftware.com/nailgun/protocol.html
  HEADER_FMT = b'>Ic'
  HEADER_LENGTH = 5

  BUFF_SIZE = 8096

  @classmethod
  def _send_chunk(cls, sock, command, payload=''):
    command_str = command.encode()
    payload_str = payload.encode()
    header = struct.pack(cls.HEADER_FMT, len(payload_str), command_str)
    sock.sendall(header + payload_str)

  def __init__(self, sock, ins, out, err):
    self._sock = sock
    self._send_chunk = partial(self._send_chunk, sock)
    self._input_reader = self._InputReader(ins, self._sock, self.BUFF_SIZE) if ins else None
    self._out = out
    self._err = err

  class _InputReader(threading.Thread):
    def __init__(self, ins, sock, buff_size):
      threading.Thread.__init__(self)
      self.daemon = True
      self._ins = ins
      self._sock = sock
      self._buff_size = buff_size
      self._send_chunk = partial(NailgunSession._send_chunk, sock)
      self._stopping = threading.Event()

    def run(self):
      while self._should_run():
        readable, _, errored = select.select([self._ins], [], [self._ins])
        if self._ins in errored:
          self.stop()
        if self._should_run() and self._ins in readable:
          data = os.read(self._ins.fileno(), self._buff_size)
          if self._should_run():
            if data:
              self._send_chunk('0', data)
            else:
              self._send_chunk('.')
              try:
                self._sock.shutdown(socket.SHUT_WR)
              except socket.error:
                # Can happen if response is quick
                pass
              self.stop()

    def stop(self):
      self._stopping.set()

    def _should_run(self):
      return not self._stopping.is_set()

  def execute(self, workdir, main_class, *args, **environment):
    for arg in args:
      self._send_chunk('A', arg)
    for k, v in environment.items():
      self._send_chunk('E', '%s=%s' % (k, v))
    self._send_chunk('D', workdir)
    self._send_chunk('C', main_class)

    if self._input_reader:
      self._input_reader.start()
    try:
      return self._read_response()
    finally:
      if self._input_reader:
        self._input_reader.stop()

  def _read_response(self):
    buff = b''
    while True:
      command, payload, buff = self._read_chunk(buff)
      if command == '1':
        self._out.write(payload)
        self._out.flush()
      elif command == '2':
        self._err.write(payload)
        self._err.flush()
      elif command == 'X':
        self._out.flush()
        self._err.flush()
        return int(payload)
      else:
        raise self.ProtocolError('Received unexpected chunk %s -> %s' % (command, payload))

  def _read_chunk(self, buff):
    while len(buff) < self.HEADER_LENGTH:
      buff += self._sock.recv(self.BUFF_SIZE)

    payload_length, command = struct.unpack(self.HEADER_FMT, buff[:self.HEADER_LENGTH])
    buff = buff[self.HEADER_LENGTH:]
    while len(buff) < payload_length:
      buff += self._sock.recv(self.BUFF_SIZE)

    payload = buff[:payload_length]
    rest = buff[payload_length:]
    return command, payload, rest


class NailgunClient(object):
  """A client for the nailgun protocol that allows execution of java binaries within a resident vm.
  """

  class NailgunError(Exception):
    """Indicates an error connecting to or interacting with a nailgun server."""

  DEFAULT_NG_HOST = 'localhost'
  DEFAULT_NG_PORT = 2113

  # For backwards compatibility with nails expecting the ng c client special env vars.
  ENV_DEFAULTS = dict(
    NAILGUN_FILESEPARATOR = os.sep,
    NAILGUN_PATHSEPARATOR = os.pathsep
  )

  def __init__(self,
               host=DEFAULT_NG_HOST,
               port=DEFAULT_NG_PORT,
               ins=sys.stdin,
               out=None,
               err=None,
               workdir=None):
    """Creates a nailgun client that can be used to issue zero or more nailgun commands.

    :param string host: the nailgun server to contact (defaults to localhost)
    :param int port: the port the nailgun server is listening on (defaults to the default nailgun
      port: 2113)
    :param file ins: a file to read command standard input from (defaults to stdin) - can be None
      in which case no input is read
    :param file out: a stream to write command standard output to (defaults to stdout)
    :param file err: a stream to write command standard error to (defaults to stderr)
    :param string workdir: the default working directory for all nailgun commands (defaults to PWD)
    """
    self._host = host
    self._port = port
    self._ins = ins
    self._out = out or sys.stdout
    self._err = err or sys.stderr
    self._workdir = workdir or os.path.abspath(os.path.curdir)

    self.execute = self.__call__

  def try_connect(self):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    return sock if sock.connect_ex((self._host, self._port)) == 0 else None

  def __call__(self, main_class, cwd=None, *args, **environment):
    """Executes the given main_class with any supplied args in the given environment.

    :param string main_class: the fully qualified class name of the main entrypoint
    :param string cwd: Set the working directory for this command
    :param list args: any arguments to pass to the main entrypoint
    :param dict environment: an environment mapping made available to native nails via the nail
      context

    Returns the exit code of the main_class.
    """
    environment = dict(self.ENV_DEFAULTS.items() + environment.items())
    cwd = cwd or self._workdir
    sock = self.try_connect()
    if not sock:
      raise self.NailgunError('Problem connecting to nailgun server'
                              ' %s:%d' % (self._host, self._port))

    session = NailgunSession(sock, self._ins, self._out, self._err)
    try:
      return session.execute(cwd, main_class, *args, **environment)
    except socket.error as e:
      raise self.NailgunError('Problem contacting nailgun server %s:%d:'
                              ' %s' % (self._host, self._port, e))
    except session.ProtocolError as e:
      raise self.NailgunError('Problem executing the nailgun protocol with nailgun server %s:%s:'
                              ' %s' % (self._host, self._port, e))
    finally:
      sock.close()

  def __repr__(self):
    return 'NailgunClient(host=%r, port=%r, workdir=%r)' % (self._host, self._port, self._workdir)
