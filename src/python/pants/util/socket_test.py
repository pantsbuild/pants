# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import inspect
import socket
import unittest
import unittest.mock

from pants.util.socket import RecvBufferedSocket, is_readable

PATCH_OPTS = dict(autospec=True, spec_set=True)


class TestSocketUtils(unittest.TestCase):
    @unittest.mock.patch("selectors.DefaultSelector", **PATCH_OPTS)
    def test_is_readable(self, mock_selector):
        mock_fileobj = unittest.mock.Mock()
        mock_selector = mock_selector.return_value.__enter__.return_value
        mock_selector.register = unittest.mock.Mock()
        # NB: the return value should actually be List[Tuple[SelectorKey, Events]], but our code only
        # cares that _some_ event happened so we choose a simpler mock here. See
        # https://docs.python.org/3/library/selectors.html#selectors.BaseSelector.select.
        mock_selector.select = unittest.mock.Mock(return_value=[(1, "")])
        self.assertTrue(is_readable(mock_fileobj, timeout=0.1))
        mock_selector.select = unittest.mock.Mock(return_value=[])
        self.assertFalse(is_readable(mock_fileobj, timeout=0.1))


class TestRecvBufferedSocket(unittest.TestCase):
    def setUp(self):
        self.chunk_size = 512
        self.mock_socket = unittest.mock.Mock()
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
        self.server_sock.sendall(b"A" * 300)
        self.assertEqual(self.buf_sock.recv(1), b"A")
        self.assertEqual(self.buf_sock.recv(200), b"A" * 200)
        self.assertEqual(self.buf_sock.recv(99), b"A" * 99)

    def test_recv_max_larger_than_buf(self):
        double_chunk = self.chunk_size * 2
        self.server_sock.sendall(b"A" * double_chunk)
        self.assertEqual(self.buf_sock.recv(double_chunk), b"A" * double_chunk)

    @unittest.mock.patch("selectors.DefaultSelector", **PATCH_OPTS)
    def test_recv_check_calls(self, mock_selector):
        mock_selector = mock_selector.return_value.__enter__.return_value
        mock_selector.register = unittest.mock.Mock()
        # NB: the return value should actually be List[Tuple[SelectorKey, Events]], but our code only
        # cares that _some_ event happened so we choose a simpler mock here. See
        # https://docs.python.org/3/library/selectors.html#selectors.BaseSelector.select.
        mock_selector.select = unittest.mock.Mock(return_value=[(1, "")])

        self.mock_socket.recv.side_effect = [b"A" * self.chunk_size, b"B" * self.chunk_size]

        self.assertEqual(self.mocked_buf_sock.recv(128), b"A" * 128)
        self.mock_socket.recv.assert_called_once_with(self.chunk_size)
        self.assertEqual(self.mocked_buf_sock.recv(128), b"A" * 128)
        self.assertEqual(self.mocked_buf_sock.recv(128), b"A" * 128)
        self.assertEqual(self.mocked_buf_sock.recv(128), b"A" * 128)
        self.assertEqual(self.mock_socket.recv.call_count, 1)

        self.assertEqual(self.mocked_buf_sock.recv(self.chunk_size), b"B" * self.chunk_size)
        self.assertEqual(self.mock_socket.recv.call_count, 2)
