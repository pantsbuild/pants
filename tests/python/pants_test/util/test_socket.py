# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import inspect
import socket
import unittest

import mock

from pants.util.socket import RecvBufferedSocket


PATCH_OPTS = dict(autospec=True, spec_set=True)


class TestRecvBufferedSocket(unittest.TestCase):
  def setUp(self):
    self.chunk_size = 512
    self.mock_socket = mock.Mock()
    self.client_sock, self.server_sock = socket.socketpair()
    self.buf_sock = RecvBufferedSocket(self.client_sock, chunk_size=self.chunk_size)
    self.mocked_buf_sock = RecvBufferedSocket(self.mock_socket, chunk_size=self.chunk_size)

  def tearDown(self):
    self.buf_sock.close()
    self.server_sock.close()

  def test_getattr(self):
    self.assertTrue(inspect.ismethod(self.buf_sock.recv))
    self.assertFalse(inspect.isbuiltin(self.buf_sock.recv))
    self.assertTrue(inspect.isbuiltin(self.buf_sock.connect))

  def test_recv(self):
    self.server_sock.sendall(b'A' * 300)
    self.assertEquals(self.buf_sock.recv(1), b'A')
    self.assertEquals(self.buf_sock.recv(200), b'A' * 200)
    self.assertEquals(self.buf_sock.recv(99), b'A' * 99)

  def test_recv_max_larger_than_buf(self):
    double_chunk = self.chunk_size * 2
    self.server_sock.sendall(b'A' * double_chunk)
    self.assertEquals(self.buf_sock.recv(double_chunk), b'A' * double_chunk)

  @mock.patch('pants.util.socket.select.select', **PATCH_OPTS)
  def test_recv_check_calls(self, mock_select):
    mock_select.return_value = ([1], [], [])
    self.mock_socket.recv.side_effect = [b'A' * self.chunk_size, b'B' * self.chunk_size]

    self.assertEquals(self.mocked_buf_sock.recv(128), b'A' * 128)
    self.mock_socket.recv.assert_called_once_with(self.chunk_size)
    self.assertEquals(self.mocked_buf_sock.recv(128), b'A' * 128)
    self.assertEquals(self.mocked_buf_sock.recv(128), b'A' * 128)
    self.assertEquals(self.mocked_buf_sock.recv(128), b'A' * 128)
    self.assertEquals(self.mock_socket.recv.call_count, 1)

    self.assertEquals(self.mocked_buf_sock.recv(self.chunk_size), b'B' * self.chunk_size)
    self.assertEquals(self.mock_socket.recv.call_count, 2)
