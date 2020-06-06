# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import socket
import unittest
import unittest.mock

from pants.java.nailgun_protocol import ChunkType, MaybeShutdownSocket, NailgunProtocol


class TestChunkType(unittest.TestCase):
    def test_chunktype_constants(self):
        self.assertIsNotNone(ChunkType.ARGUMENT)
        self.assertIsNotNone(ChunkType.ENVIRONMENT)
        self.assertIsNotNone(ChunkType.WORKING_DIR)
        self.assertIsNotNone(ChunkType.COMMAND)
        self.assertIsNotNone(ChunkType.STDIN)
        self.assertIsNotNone(ChunkType.STDOUT)
        self.assertIsNotNone(ChunkType.STDERR)
        self.assertIsNotNone(ChunkType.START_READING_INPUT)
        self.assertIsNotNone(ChunkType.STDIN_EOF)
        self.assertIsNotNone(ChunkType.EXIT)


class TestNailgunProtocol(unittest.TestCase):
    EMPTY_PAYLOAD = ""
    TEST_COMMAND = "test"
    TEST_OUTPUT = "t e s t"
    TEST_UNICODE_PAYLOAD = r"([\d０-９]{1,4}\s?[年月日])".encode()
    TEST_WORKING_DIR = "/path/to/a/repo"
    TEST_ARGUMENTS = ["t", "e", "s", "t"]
    TEST_ENVIRON = dict(TEST_VAR="success")

    def setUp(self):
        self.client_sock, self.server_sock = socket.socketpair()

    def tearDown(self):
        self.client_sock.close()
        self.server_sock.close()

    def test_send_and_parse_request(self):
        # Send a test request over the client socket.
        NailgunProtocol.send_request(
            self.client_sock,
            self.TEST_WORKING_DIR,
            self.TEST_COMMAND,
            *self.TEST_ARGUMENTS,
            **self.TEST_ENVIRON
        )

        # Receive the request from the server-side context.
        working_dir, command, arguments, environment = NailgunProtocol.parse_request(
            self.server_sock
        )

        self.assertEqual(working_dir, self.TEST_WORKING_DIR)
        self.assertEqual(command, self.TEST_COMMAND)
        self.assertEqual(arguments, self.TEST_ARGUMENTS)
        self.assertEqual(environment, self.TEST_ENVIRON)

    def test_send_and_parse_request_bad_chunktype(self):
        INVALID_CHUNK_TYPE = b";"
        NailgunProtocol.write_chunk(self.client_sock, INVALID_CHUNK_TYPE, "1729")

        with self.assertRaises(NailgunProtocol.ProtocolError):
            NailgunProtocol.parse_request(self.server_sock)

    def test_read_until(self):
        recv_chunks = [b"1", b"234", b"56", b"789", b"0"]
        mock_socket = unittest.mock.Mock()
        mock_socket.recv.side_effect = recv_chunks
        self.assertEqual(NailgunProtocol._read_until(mock_socket, 10), b"1234567890")
        self.assertEqual(mock_socket.recv.call_count, len(recv_chunks))

    def test_read_until_truncated_recv(self):
        self.server_sock.sendall(b"x")
        self.server_sock.close()

        with self.assertRaises(NailgunProtocol.TruncatedRead):
            NailgunProtocol._read_until(self.client_sock, 3)

    def test_iter_chunks(self):
        expected_chunks = [
            (ChunkType.COMMAND, self.TEST_COMMAND),
            (ChunkType.STDOUT, self.TEST_OUTPUT),
            (ChunkType.STDERR, self.TEST_OUTPUT),
            (ChunkType.EXIT, self.EMPTY_PAYLOAD)
            # N.B. without an EXIT chunk here (or socket failure), this test will deadlock in iter_chunks.
        ]

        for chunk_type, payload in expected_chunks:
            NailgunProtocol.write_chunk(self.server_sock, chunk_type, payload)

        for i, chunk in enumerate(
            NailgunProtocol.iter_chunks(MaybeShutdownSocket(self.client_sock))
        ):
            self.assertEqual(chunk, expected_chunks[i])

    def test_read_and_write_chunk(self):
        # Write a command chunk to the server socket.
        NailgunProtocol.write_chunk(self.server_sock, ChunkType.COMMAND, self.TEST_COMMAND)

        # Read the chunk from the client socket.
        chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock)

        self.assertEqual((chunk_type, payload), (ChunkType.COMMAND, self.TEST_COMMAND))

    def test_read_chunk_truncated_during_header(self):
        """Construct a chunk and truncate to the first 3 bytes ([:3]), an incomplete header."""
        truncated_chunk = NailgunProtocol.construct_chunk(ChunkType.STDOUT, self.TEST_OUTPUT)[:3]
        self.server_sock.sendall(truncated_chunk)
        self.server_sock.close()

        with self.assertRaises(NailgunProtocol.TruncatedHeaderError):
            NailgunProtocol.read_chunk(self.client_sock)

    def test_read_chunk_truncated_before_payload(self):
        """Construct a chunk and send exactly the header (first 5 bytes) and truncate the
        remainder."""
        truncated_chunk = NailgunProtocol.construct_chunk(ChunkType.STDOUT, self.TEST_OUTPUT)[:5]
        self.server_sock.sendall(truncated_chunk)
        self.server_sock.close()

        with self.assertRaises(NailgunProtocol.TruncatedPayloadError):
            NailgunProtocol.read_chunk(self.client_sock)

    def test_read_chunk_truncated_during_payload(self):
        """Construct a chunk and truncate the last 3 bytes of the payload ([:-3])."""
        truncated_chunk = NailgunProtocol.construct_chunk(ChunkType.STDOUT, self.TEST_OUTPUT)[:-3]
        self.server_sock.sendall(truncated_chunk)
        self.server_sock.close()

        with self.assertRaises(NailgunProtocol.TruncatedPayloadError):
            NailgunProtocol.read_chunk(self.client_sock)

    def test_send_start_reading_input(self):
        NailgunProtocol.send_start_reading_input(self.server_sock)
        chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock)
        self.assertEqual((chunk_type, payload), (ChunkType.START_READING_INPUT, self.EMPTY_PAYLOAD))

    def test_send_stdout(self):
        NailgunProtocol.send_stdout(self.server_sock, self.TEST_OUTPUT)
        chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock)
        self.assertEqual((chunk_type, payload), (ChunkType.STDOUT, self.TEST_OUTPUT))

    def test_send_stderr(self):
        NailgunProtocol.send_stderr(self.server_sock, self.TEST_OUTPUT)
        chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock)
        self.assertEqual((chunk_type, payload), (ChunkType.STDERR, self.TEST_OUTPUT))

    def test_send_exit_default(self):
        NailgunProtocol.send_exit(self.server_sock)
        chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock)
        self.assertEqual((chunk_type, payload), (ChunkType.EXIT, self.EMPTY_PAYLOAD))

    def test_send_exit(self):
        NailgunProtocol.send_exit(self.server_sock, self.TEST_OUTPUT)
        chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock)
        self.assertEqual((chunk_type, payload), (ChunkType.EXIT, self.TEST_OUTPUT))

    def test_send_exit_with_code(self):
        return_code = 1
        NailgunProtocol.send_exit_with_code(self.server_sock, return_code)
        chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock, return_bytes=True)
        self.assertEqual(
            (chunk_type, payload), (ChunkType.EXIT, NailgunProtocol.encode_int(return_code))
        )

    def test_send_unicode_chunk(self):
        NailgunProtocol.send_stdout(self.server_sock, self.TEST_UNICODE_PAYLOAD)
        chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock, return_bytes=True)
        self.assertEqual((chunk_type, payload), (ChunkType.STDOUT, self.TEST_UNICODE_PAYLOAD))

    def test_ttynames_from_empty_env(self):
        self.assertEqual(NailgunProtocol.ttynames_from_env({}), (None, None, None))

    def _make_mock_stream(self, isatty, fileno):
        mock_stream = unittest.mock.Mock()
        mock_stream.isatty.return_value = isatty
        mock_stream.fileno.return_value = fileno
        return mock_stream

    _fake_ttyname = "/this/is/not/a/real/tty"

    @unittest.mock.patch("os.ttyname", autospec=True, spec_set=True)
    def test_ttynames_to_env_with_mock_tty(self, mock_ttyname):
        mock_ttyname.return_value = self._fake_ttyname
        mock_stdin = self._make_mock_stream(True, 0)
        mock_stdout = self._make_mock_stream(False, 1)
        mock_stderr = self._make_mock_stream(True, 2)

        env = NailgunProtocol.ttynames_to_env(mock_stdin, mock_stdout, mock_stderr)
        self.assertEqual(
            env,
            {"NAILGUN_TTY_PATH_0": self._fake_ttyname, "NAILGUN_TTY_PATH_2": self._fake_ttyname,},
        )
        self.assertEqual(
            NailgunProtocol.ttynames_from_env(env), (self._fake_ttyname, None, self._fake_ttyname),
        )

    def test_construct_chunk(self):
        with self.assertRaises(TypeError):
            NailgunProtocol.construct_chunk(ChunkType.STDOUT, 1111)

    def test_construct_chunk_unicode(self):
        NailgunProtocol.construct_chunk(ChunkType.STDOUT, u"Ø")

    def test_construct_chunk_bytes(self):
        NailgunProtocol.construct_chunk(ChunkType.STDOUT, b"yes")
