# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import socket
import threading
import unittest
import unittest.mock
from contextlib import contextmanager
from socketserver import TCPServer

from pants.java.nailgun_protocol import ChunkType, MaybeShutdownSocket, NailgunProtocol
from pants.pantsd.pailgun_server import PailgunHandler, PailgunServer

PATCH_OPTS = dict(autospec=True, spec_set=True)


class TestPailgunServer(unittest.TestCase):
    def setUp(self):
        self.mock_handler_inst = unittest.mock.Mock()
        self.fake_environment = {}
        self.mock_handler_inst.parsed_request.return_value = (None, None, [], self.fake_environment)

        self.mock_runner_factory = unittest.mock.Mock(
            side_effect=Exception("this should never be called")
        )
        self.mock_handler_class = unittest.mock.Mock(return_value=self.mock_handler_inst)
        self.lock = threading.RLock()

        @contextmanager
        def lock():
            with self.lock:
                yield

        self.after_request_callback_calls = 0

        def after_request_callback():
            self.after_request_callback_calls += 1

        with unittest.mock.patch.object(PailgunServer, "server_bind"), unittest.mock.patch.object(
            PailgunServer, "server_activate"
        ):
            self.server = PailgunServer(
                server_address=("0.0.0.0", 0),
                runner_factory=self.mock_runner_factory,
                handler_class=self.mock_handler_class,
                lifecycle_lock=lock,
                request_complete_callback=after_request_callback,
            )

    @unittest.mock.patch.object(TCPServer, "server_bind", **PATCH_OPTS)
    def test_server_bind(self, mock_tcpserver_bind):
        mock_sock = unittest.mock.Mock()
        mock_sock.getsockname.return_value = ("0.0.0.0", 31337)
        self.server.socket = mock_sock
        self.server.server_bind()
        self.assertEqual(self.server.server_port, 31337)
        self.assertIs(mock_tcpserver_bind.called, True)

    @unittest.mock.patch.object(PailgunServer, "close_request", **PATCH_OPTS)
    def test_process_request_thread(self, mock_close_request):
        mock_request = unittest.mock.Mock()
        self.server.process_request_thread(mock_request, ("1.2.3.4", 31338))
        self.assertIs(self.mock_handler_inst.handle_request.called, True)
        mock_close_request.assert_called_once_with(self.server, mock_request)

    @unittest.mock.patch.object(PailgunServer, "close_request", **PATCH_OPTS)
    def test_process_request_calls_callback(self, mock_close_request):
        mock_request = unittest.mock.Mock()
        self.server.process_request_thread(mock_request, ("1.2.3.4", 31338))
        self.assertIs(self.mock_handler_inst.handle_request.called, True)
        assert self.after_request_callback_calls == 1

    @unittest.mock.patch.object(PailgunServer, "shutdown_request", **PATCH_OPTS)
    def test_process_request_thread_error(self, mock_shutdown_request):
        mock_request = unittest.mock.Mock()
        self.mock_handler_inst.handle_request.side_effect = AttributeError("oops")
        self.server.process_request_thread(mock_request, ("1.2.3.4", 31338))
        self.assertIs(self.mock_handler_inst.handle_request.called, True)
        self.assertIs(self.mock_handler_inst.handle_error.called, True)
        mock_shutdown_request.assert_called_once_with(self.server, mock_request)


class TestPailgunHandler(unittest.TestCase):
    def setUp(self):
        self.client_sock, self.server_sock = socket.socketpair()
        self.mock_socket = unittest.mock.Mock()
        self.mock_server = unittest.mock.create_autospec(PailgunServer, spec_set=True)
        self.handler = PailgunHandler(
            self.server_sock, self.client_sock.getsockname()[:2], self.mock_server
        )

    def test_handle_error(self):
        self.handler.handle_error()
        maybe_shutdown_socket = MaybeShutdownSocket(self.client_sock)
        last_chunk_type, last_payload = list(NailgunProtocol.iter_chunks(maybe_shutdown_socket))[-1]
        self.assertEqual(last_chunk_type, ChunkType.EXIT)
        self.assertEqual(last_payload, "1")

    @unittest.mock.patch.object(PailgunHandler, "_run_pants", **PATCH_OPTS)
    def test_handle_request(self, mock_run_pants):
        NailgunProtocol.send_request(self.client_sock, "/test", "./pants", "help-advanced")
        self.handler.handle_request()
        self.assertIs(mock_run_pants.called, True)
