# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import inspect
import os
import socket
import unittest
from contextlib import contextmanager

import mock

from pants.java.nailgun_client import NailgunClient, NailgunClientSession
from pants.java.nailgun_io import NailgunStreamReader
from pants.java.nailgun_protocol import ChunkType, NailgunProtocol


PATCH_OPTS = dict(autospec=True, spec_set=True)


class FakeFile(object):
  def __init__(self):
    self.content = b''

  def write(self, val):
    self.content += val

  def fileno(self):
    return -1

  def flush(self):
    return


class TestNailgunClientSession(unittest.TestCase):
  BAD_CHUNK_TYPE = b';'
  TEST_PAYLOAD = 't e s t'
  TEST_WORKING_DIR = '/test_working_dir'
  TEST_MAIN_CLASS = 'test_main_class'
  TEST_ARGUMENTS = ['t', 'e', 's', 't']
  TEST_ENVIRON = dict(TEST_ENV_VAR='xyz')

  def setUp(self):
    self.client_sock, self.server_sock = socket.socketpair()

    self.fake_stdout = FakeFile()
    self.fake_stderr = FakeFile()

    self.nailgun_client_session = NailgunClientSession(
      sock=self.client_sock,
      in_fd=None,
      out_fd=self.fake_stdout,
      err_fd=self.fake_stderr
    )

    self.mock_reader = mock.create_autospec(NailgunStreamReader, spec_set=True)
    self.nailgun_client_session._input_reader = self.mock_reader

  def tearDown(self):
    self.server_sock.close()
    self.client_sock.close()

  def test_maybe_input_reader_running(self):
    with self.nailgun_client_session._maybe_input_reader_running():
      self.mock_reader.start.assert_called_once_with()
    self.mock_reader.stop.assert_called_once_with()

  def test_process_session(self):
    NailgunProtocol.write_chunk(self.server_sock, ChunkType.STDOUT, self.TEST_PAYLOAD)
    NailgunProtocol.write_chunk(self.server_sock, ChunkType.STDERR, self.TEST_PAYLOAD)
    NailgunProtocol.write_chunk(self.server_sock, ChunkType.STDERR, self.TEST_PAYLOAD)
    NailgunProtocol.write_chunk(self.server_sock, ChunkType.STDOUT, self.TEST_PAYLOAD)
    NailgunProtocol.write_chunk(self.server_sock, ChunkType.STDERR, self.TEST_PAYLOAD)
    NailgunProtocol.write_chunk(self.server_sock, ChunkType.EXIT, '1729')
    self.assertEquals(self.nailgun_client_session._process_session(), 1729)
    self.assertEquals(self.fake_stdout.content, self.TEST_PAYLOAD * 2)
    self.assertEquals(self.fake_stderr.content, self.TEST_PAYLOAD * 3)

  def test_process_session_bad_chunk(self):
    NailgunProtocol.write_chunk(self.server_sock, self.BAD_CHUNK_TYPE, '')

    with self.assertRaises(NailgunClientSession.ProtocolError):
      self.nailgun_client_session._process_session()

  @mock.patch.object(NailgunClientSession, '_process_session', **PATCH_OPTS)
  @mock.patch.object(NailgunClientSession, '_maybe_input_reader_running', **PATCH_OPTS)
  def test_execute(self, mctx, mproc):
    mproc.return_value = self.TEST_PAYLOAD
    out = self.nailgun_client_session.execute(
      self.TEST_WORKING_DIR,
      self.TEST_MAIN_CLASS,
      *self.TEST_ARGUMENTS,
      **self.TEST_ENVIRON
    )
    self.assertEquals(out, self.TEST_PAYLOAD)
    mctx.assert_called_once_with(self.nailgun_client_session)
    mproc.assert_called_once_with(self.nailgun_client_session)


class TestNailgunClient(unittest.TestCase):
  def setUp(self):
    self.nailgun_client = NailgunClient()

  @mock.patch('pants.java.nailgun_client.RecvBufferedSocket', **PATCH_OPTS)
  def test_try_connect(self, mock_socket_cls):
    mock_socket = mock.Mock()
    mock_socket_cls.return_value = mock_socket

    self.assertEquals(self.nailgun_client.try_connect(), mock_socket)

    self.assertEquals(mock_socket_cls.call_count, 1)
    mock_socket.connect.assert_called_once_with(
      (NailgunClient.DEFAULT_NG_HOST, NailgunClient.DEFAULT_NG_PORT)
    )

  @mock.patch('pants.java.nailgun_client.RecvBufferedSocket', **PATCH_OPTS)
  def test_try_connect_socket_error(self, mock_socket_cls):
    mock_socket = mock.Mock()
    mock_socket.connect.side_effect = socket.error()
    mock_socket_cls.return_value = mock_socket

    with self.assertRaises(NailgunClient.NailgunConnectionError):
      self.nailgun_client.try_connect()

  @mock.patch.object(NailgunClient, 'try_connect', **PATCH_OPTS)
  @mock.patch('pants.java.nailgun_client.NailgunClientSession', **PATCH_OPTS)
  def test_execute(self, mock_session, mock_try_connect):
    self.nailgun_client.execute('test')
    self.assertEquals(mock_try_connect.call_count, 1)
    self.assertEquals(mock_session.call_count, 1)

  @mock.patch.object(NailgunClient, 'try_connect', **PATCH_OPTS)
  @mock.patch('pants.java.nailgun_client.NailgunClientSession', **PATCH_OPTS)
  def test_execute_propagates_connection_error_on_connect(self, mock_session, mock_try_connect):
    mock_try_connect.side_effect = NailgunClient.NailgunConnectionError('oops')

    with self.assertRaises(NailgunClient.NailgunConnectionError):
      self.nailgun_client.execute('test')

  @mock.patch.object(NailgunClient, 'try_connect', **PATCH_OPTS)
  @mock.patch('pants.java.nailgun_client.NailgunClientSession', **PATCH_OPTS)
  def test_execute_socketerror_on_execute(self, mock_session, mock_try_connect):
    mock_session.return_value.execute.side_effect = socket.error('oops')

    with self.assertRaises(NailgunClient.NailgunError):
      self.nailgun_client.execute('test')

  @mock.patch.object(NailgunClient, 'try_connect', **PATCH_OPTS)
  @mock.patch('pants.java.nailgun_client.NailgunClientSession', **PATCH_OPTS)
  def test_execute_protocolerror_on_execute(self, mock_session, mock_try_connect):
    mock_session.return_value.ProtocolError = NailgunProtocol.ProtocolError
    mock_session.return_value.execute.side_effect = NailgunProtocol.ProtocolError('oops')

    with self.assertRaises(NailgunClient.NailgunError):
      self.nailgun_client.execute('test')

  def test_repr(self):
    self.assertIsNotNone(repr(self.nailgun_client))
