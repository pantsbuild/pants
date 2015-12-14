# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import socket
import unittest

import mock

from pants.java.nailgun_protocol import ChunkType, NailgunProtocol


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
  EMPTY_PAYLOAD = ''
  TEST_COMMAND = 'test'
  TEST_OUTPUT = 't e s t'
  TEST_WORKING_DIR = '/path/to/a/repo'
  TEST_ARGUMENTS = ['t', 'e', 's', 't']
  TEST_ENVIRON = dict(TEST_VAR='success')

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
    working_dir, command, arguments, environment = NailgunProtocol.parse_request(self.server_sock)

    self.assertEqual(working_dir, self.TEST_WORKING_DIR)
    self.assertEqual(command, self.TEST_COMMAND)
    self.assertEqual(arguments, self.TEST_ARGUMENTS)
    self.assertEqual(environment, self.TEST_ENVIRON)

  def test_send_and_parse_request_bad_chunktype(self):
    INVALID_CHUNK_TYPE = b';'
    NailgunProtocol.write_chunk(self.client_sock, INVALID_CHUNK_TYPE, '1729')

    with self.assertRaises(NailgunProtocol.ProtocolError):
      NailgunProtocol.parse_request(self.server_sock)

  def test_read_until(self):
    recv_chunks = ['1', '234', '56', '789', '0']
    mock_socket = mock.Mock()
    mock_socket.recv.side_effect = recv_chunks
    self.assertEqual(NailgunProtocol._read_until(mock_socket, 10), '1234567890')
    self.assertEqual(mock_socket.recv.call_count, len(recv_chunks))

  def test_read_until_truncated_recv(self):
    self.server_sock.sendall(b'x')
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

    for i, chunk in enumerate(NailgunProtocol.iter_chunks(self.client_sock)):
      self.assertEqual(chunk, expected_chunks[i])

  def test_read_and_write_chunk(self):
    # Write a command chunk to the server socket.
    NailgunProtocol.write_chunk(self.server_sock, ChunkType.COMMAND, self.TEST_COMMAND)

    # Read the chunk from the client socket.
    chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock)

    self.assertEqual(
      (chunk_type, payload),
      (ChunkType.COMMAND, self.TEST_COMMAND)
    )

  def test_read_chunk_truncated_during_header(self):
    """Construct a chunk and truncate to the first 3 bytes ([:3]), an incomplete header."""
    truncated_chunk = NailgunProtocol.construct_chunk(ChunkType.STDOUT, self.TEST_OUTPUT)[:3]
    self.server_sock.sendall(truncated_chunk)
    self.server_sock.close()

    with self.assertRaises(NailgunProtocol.TruncatedHeaderError):
      NailgunProtocol.read_chunk(self.client_sock)

  def test_read_chunk_truncated_before_payload(self):
    """Construct a chunk and send exactly the header (first 5 bytes) and truncate the remainder."""
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
    self.assertEqual(
      (chunk_type, payload),
      (ChunkType.START_READING_INPUT, self.EMPTY_PAYLOAD)
    )

  def test_send_stdout(self):
    NailgunProtocol.send_stdout(self.server_sock, self.TEST_OUTPUT)
    chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock)
    self.assertEqual(
      (chunk_type, payload),
      (ChunkType.STDOUT, self.TEST_OUTPUT)
    )

  def test_send_stderr(self):
    NailgunProtocol.send_stderr(self.server_sock, self.TEST_OUTPUT)
    chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock)
    self.assertEqual(
      (chunk_type, payload),
      (ChunkType.STDERR, self.TEST_OUTPUT)
    )

  def test_send_exit_default(self):
    NailgunProtocol.send_exit(self.server_sock)
    chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock)
    self.assertEqual(
      (chunk_type, payload),
      (ChunkType.EXIT, self.EMPTY_PAYLOAD)
    )

  def test_send_exit(self):
    NailgunProtocol.send_exit(self.server_sock, self.TEST_OUTPUT)
    chunk_type, payload = NailgunProtocol.read_chunk(self.client_sock)
    self.assertEqual(
      (chunk_type, payload),
      (ChunkType.EXIT, self.TEST_OUTPUT)
    )

  def test_isatty_from_empty_env(self):
    self.assertEquals(NailgunProtocol.isatty_from_env({}), (False, False, False))

  def test_isatty_from_env(self):
    self.assertEquals(
      NailgunProtocol.isatty_from_env({
        'NAILGUN_TTY_0': '1',
        'NAILGUN_TTY_1': '0',
        'NAILGUN_TTY_2': '1'
      }),
      (True, False, True)
    )

  def test_isatty_from_env_mixed(self):
    self.assertEquals(
      NailgunProtocol.isatty_from_env({
        'NAILGUN_TTY_0': '0',
        'NAILGUN_TTY_1': '1'
      }),
      (False, True, False)
    )

  def test_construct_chunk(self):
    with self.assertRaises(TypeError):
      NailgunProtocol.construct_chunk(ChunkType.STDOUT, 1111)

  def test_construct_chunk_unicode(self):
    NailgunProtocol.construct_chunk(ChunkType.STDOUT, u'Ø')

  def test_construct_chunk_bytes(self):
    NailgunProtocol.construct_chunk(ChunkType.STDOUT, b'yes')
