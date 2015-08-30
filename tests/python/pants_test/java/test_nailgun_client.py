# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import socket
import struct
import unittest
from contextlib import contextmanager

from pants.java.nailgun_client import NailgunSession


class FakeWritableFile(object):
  def __init__(self):
    self.content = b''

  def write(self, val):
    self.content += val

  def flush(self):
    pass


class NailgunSessionTest(unittest.TestCase):
  def setUp(self):
    self.client_socket, self.ng_socket = socket.socketpair()
    self.outfile = FakeWritableFile()
    self.errfile = FakeWritableFile()
    self.ng_session = NailgunSession(self.client_socket, None, self.outfile, self.errfile)

  def test_socket_closed_before_header(self):
    # Send some simple messages to exercise the loop first, to make
    # sure we're not always erroring.
    stdout_header = struct.pack(NailgunSession.HEADER_FMT, 6, b'1')
    self.ng_socket.send(stdout_header)
    self.ng_socket.send(b'foozle')
    exit_header = struct.pack(NailgunSession.HEADER_FMT, 3, b'X')
    self.ng_socket.send(exit_header)
    self.ng_socket.send(b'123')
    self.assertEquals(self.ng_session._read_response(), 123)
    self.assertEquals(self.outfile.content, b'foozle')

    self.ng_socket.close()
    with self.assertRaises(NailgunSession.TruncatedHeaderError):
      self.ng_session._read_response()

  def test_socket_closed_during_header(self):
    stdout_header = struct.pack(NailgunSession.HEADER_FMT, 6, b'1')
    self.ng_socket.send(stdout_header[:2])

    self.ng_socket.close()
    with self.assertRaises(NailgunSession.TruncatedHeaderError):
      self.ng_session._read_response()

  def test_socket_closed_before_payload(self):
    stdout_header = struct.pack(NailgunSession.HEADER_FMT, 6, b'1')
    self.ng_socket.send(stdout_header)

    self.ng_socket.close()
    with self.assertRaises(NailgunSession.TruncatedPayloadError):
      self.ng_session._read_response()

  def test_socket_closed_during_payload(self):
    stdout_header = struct.pack(NailgunSession.HEADER_FMT, 6, b'1')
    self.ng_socket.send(stdout_header)
    self.ng_socket.send(b'foo')

    self.ng_socket.close()
    with self.assertRaises(NailgunSession.TruncatedPayloadError):
      self.ng_session._read_response()
