# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import signal
import socket
import unittest
import unittest.mock

from pants.java.nailgun_client import NailgunClient, NailgunClientSession
from pants.java.nailgun_io import NailgunStreamWriter
from pants.java.nailgun_protocol import ChunkType, NailgunProtocol

PATCH_OPTS = dict(autospec=True, spec_set=True)


class FakeFile:
    def __init__(self):
        self.content = b""

    def write(self, val):
        self.content += val

    def fileno(self):
        return -1

    def flush(self):
        return


class TestNailgunClientSession(unittest.TestCase):
    BAD_CHUNK_TYPE = b";"
    TEST_PAYLOAD = b"t e s t"
    TEST_WORKING_DIR = "/test_working_dir"
    TEST_MAIN_CLASS = "test_main_class"
    TEST_ARGUMENTS = [b"t", b"e", b"s", b"t"]
    TEST_ENVIRON = dict(TEST_ENV_VAR="xyz")

    def setUp(self):
        self.client_sock, self.server_sock = socket.socketpair()

        self.fake_stdout = FakeFile()
        self.fake_stderr = FakeFile()

        self.nailgun_client_session = NailgunClientSession(
            sock=self.client_sock,
            in_file=None,
            out_file=self.fake_stdout,
            err_file=self.fake_stderr,
        )

        self.mock_stdin_reader = unittest.mock.create_autospec(NailgunStreamWriter, spec_set=True)
        self.mock_stdin_reader.is_alive.side_effect = [False, True]
        self.nailgun_client_session._input_writer = self.mock_stdin_reader

    def tearDown(self):
        self.server_sock.close()
        self.client_sock.close()

    def test_input_writer_start_stop(self):
        self.nailgun_client_session._maybe_start_input_writer()
        self.mock_stdin_reader.start.assert_called_once_with()

        self.nailgun_client_session._maybe_stop_input_writer()
        self.mock_stdin_reader.stop.assert_called_once_with()

    def test_input_writer_noop(self):
        self.nailgun_client_session._input_writer = None
        self.nailgun_client_session._maybe_start_input_writer()
        self.nailgun_client_session._maybe_stop_input_writer()

    @unittest.mock.patch("psutil.Process", **PATCH_OPTS)
    def test_process_session(self, mock_psutil_process):
        mock_psutil_process.cmdline.return_value = ["mock", "process"]
        NailgunProtocol.write_chunk(self.server_sock, ChunkType.START_READING_INPUT)
        NailgunProtocol.write_chunk(self.server_sock, ChunkType.STDOUT, self.TEST_PAYLOAD)
        NailgunProtocol.write_chunk(self.server_sock, ChunkType.STDERR, self.TEST_PAYLOAD)
        NailgunProtocol.write_chunk(self.server_sock, ChunkType.STDERR, self.TEST_PAYLOAD)
        NailgunProtocol.write_chunk(self.server_sock, ChunkType.STDOUT, self.TEST_PAYLOAD)
        NailgunProtocol.write_chunk(self.server_sock, ChunkType.STDERR, self.TEST_PAYLOAD)
        NailgunProtocol.write_chunk(self.server_sock, ChunkType.EXIT, b"1729")
        self.assertEqual(self.nailgun_client_session._process_session(), 1729)
        self.assertEqual(self.fake_stdout.content, self.TEST_PAYLOAD * 2)
        self.assertEqual(self.fake_stderr.content, self.TEST_PAYLOAD * 3)
        self.mock_stdin_reader.start.assert_called_once_with()
        self.mock_stdin_reader.stop.assert_called_once_with()

    @unittest.mock.patch("psutil.Process", **PATCH_OPTS)
    def test_process_session_bad_chunk(self, mock_psutil_process):
        mock_psutil_process.cmdline.return_value = ["mock", "process"]
        NailgunProtocol.write_chunk(self.server_sock, ChunkType.START_READING_INPUT)
        NailgunProtocol.write_chunk(self.server_sock, self.BAD_CHUNK_TYPE, "")

        with self.assertRaises(NailgunClientSession.ProtocolError):
            self.nailgun_client_session._process_session()

        self.mock_stdin_reader.start.assert_called_once_with()
        self.mock_stdin_reader.stop.assert_called_once_with()

    @unittest.mock.patch.object(NailgunClientSession, "_process_session", **PATCH_OPTS)
    def test_execute(self, mock_process_session):
        mock_process_session.return_value = self.TEST_PAYLOAD
        out = self.nailgun_client_session.execute(
            self.TEST_WORKING_DIR, self.TEST_MAIN_CLASS, *self.TEST_ARGUMENTS, **self.TEST_ENVIRON
        )
        self.assertEqual(out, self.TEST_PAYLOAD)
        mock_process_session.assert_called_once_with(self.nailgun_client_session)


class TestNailgunClient(unittest.TestCase):
    def setUp(self):
        self.nailgun_client = NailgunClient()

    @unittest.mock.patch("pants.java.nailgun_client.RecvBufferedSocket", **PATCH_OPTS)
    def test_try_connect(self, mock_socket_cls):
        mock_socket = unittest.mock.Mock()
        mock_socket_cls.return_value = mock_socket

        self.assertEqual(self.nailgun_client.try_connect(), mock_socket)

        self.assertEqual(mock_socket_cls.call_count, 1)
        mock_socket.connect.assert_called_once_with(
            (NailgunClient.DEFAULT_NG_HOST, NailgunClient.DEFAULT_NG_PORT)
        )

    @unittest.mock.patch("pants.java.nailgun_client.RecvBufferedSocket", **PATCH_OPTS)
    def test_try_connect_socket_error(self, mock_socket_cls):
        mock_socket = unittest.mock.Mock()
        mock_socket.connect.side_effect = socket.error()
        mock_socket_cls.return_value = mock_socket

        with self.assertRaises(NailgunClient.NailgunConnectionError):
            self.nailgun_client.try_connect()

    @unittest.mock.patch.object(NailgunClient, "try_connect", **PATCH_OPTS)
    @unittest.mock.patch("pants.java.nailgun_client.NailgunClientSession", **PATCH_OPTS)
    def test_execute(self, mock_session, mock_try_connect):
        self.nailgun_client.execute("test", [])
        self.assertEqual(mock_try_connect.call_count, 1)
        self.assertEqual(mock_session.call_count, 1)

    @unittest.mock.patch.object(NailgunClient, "try_connect", **PATCH_OPTS)
    @unittest.mock.patch("pants.java.nailgun_client.NailgunClientSession", **PATCH_OPTS)
    def test_execute_propagates_connection_error_on_connect(self, mock_session, mock_try_connect):
        mock_try_connect.side_effect = NailgunClient.NailgunConnectionError(
            "127.0.0.1:31337", Exception("oops"),
        )

        with self.assertRaises(NailgunClient.NailgunConnectionError):
            self.nailgun_client.execute("test", [])

    @unittest.mock.patch.object(NailgunClient, "try_connect", **PATCH_OPTS)
    @unittest.mock.patch("pants.java.nailgun_client.NailgunClientSession", **PATCH_OPTS)
    def test_execute_socketerror_on_execute(self, mock_session, mock_try_connect):
        mock_session.return_value.execute.side_effect = socket.error("oops")

        with self.assertRaises(NailgunClient.NailgunError):
            self.nailgun_client.execute("test", [])

    @unittest.mock.patch.object(NailgunClient, "try_connect", **PATCH_OPTS)
    @unittest.mock.patch("pants.java.nailgun_client.NailgunClientSession", **PATCH_OPTS)
    def test_execute_protocolerror_on_execute(self, mock_session, mock_try_connect):
        mock_session.return_value.ProtocolError = NailgunProtocol.ProtocolError
        mock_session.return_value.execute.side_effect = NailgunProtocol.ProtocolError("oops")

        with self.assertRaises(NailgunClient.NailgunError):
            self.nailgun_client.execute("test", [])

    def test_repr(self):
        self.assertIsNotNone(repr(self.nailgun_client))

    @unittest.mock.patch("os.kill", **PATCH_OPTS)
    def test_send_control_c(self, mock_kill):
        self.nailgun_client.remote_pid = 31337
        self.nailgun_client.maybe_send_signal(signal.SIGINT)
        mock_kill.assert_has_calls([unittest.mock.call(31337, signal.SIGINT)])
