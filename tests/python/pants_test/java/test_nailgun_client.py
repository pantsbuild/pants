# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re
import signal
import socket
import unittest
from builtins import object

import mock

from pants.java.nailgun_client import PailgunClient, PailgunClientSession
from pants.java.nailgun_io import NailgunStreamWriter
from pants.java.nailgun_protocol import NailgunProtocol, PailgunProtocol


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


class TestPailgunClientSession(unittest.TestCase):
  BAD_CHUNK_TYPE = b';'
  TEST_PAYLOAD = b't e s t'
  TEST_EXIT_CODE = 13
  TEST_WORKING_DIR = '/test_working_dir'
  TEST_MAIN_CLASS = 'test_main_class'
  TEST_ARGUMENTS = [b't', b'e', b's', b't']
  TEST_ENVIRON = dict(TEST_ENV_VAR='xyz')

  def setUp(self):
    self.client_sock, self.server_sock = socket.socketpair()

    self.fake_stdout = FakeFile()
    self.fake_stderr = FakeFile()

    self.pailgun_client_session = PailgunClientSession(
      sock=self.client_sock,
      in_file=None,
      out_file=self.fake_stdout,
      err_file=self.fake_stderr
    )

    self.mock_stdin_reader = mock.create_autospec(NailgunStreamWriter, spec_set=True)
    self.mock_stdin_reader.is_alive.side_effect = [False, True]
    self.pailgun_client_session._input_writer = self.mock_stdin_reader

  def tearDown(self):
    self.server_sock.close()
    self.client_sock.close()

  def test_input_writer_start_stop(self):
    self.pailgun_client_session._maybe_start_input_writer()
    self.mock_stdin_reader.start.assert_called_once_with()

    self.pailgun_client_session._maybe_stop_input_writer()
    self.mock_stdin_reader.stop.assert_called_once_with()

  def test_input_writer_noop(self):
    self.pailgun_client_session._input_writer = None
    self.pailgun_client_session._maybe_start_input_writer()
    self.pailgun_client_session._maybe_stop_input_writer()

  def test_process_session(self):
    PailgunProtocol.send_pid(self.server_sock, 31337)
    PailgunProtocol.send_pgrp(self.server_sock, -31336)
    PailgunProtocol.send_start_reading_input(self.server_sock)
    PailgunProtocol.send_stdout(self.server_sock, self.TEST_PAYLOAD)
    PailgunProtocol.send_stderr(self.server_sock, self.TEST_PAYLOAD)
    PailgunProtocol.send_stderr(self.server_sock, self.TEST_PAYLOAD)
    PailgunProtocol.send_stdout(self.server_sock, self.TEST_PAYLOAD)
    PailgunProtocol.send_stderr(self.server_sock, self.TEST_PAYLOAD)
    PailgunProtocol.send_exit_with_code(self.server_sock, 1729)

    with self.pailgun_client_session.negotiate(
        self.TEST_WORKING_DIR,
        self.TEST_MAIN_CLASS,
        *self.TEST_ARGUMENTS,
        **self.TEST_ENVIRON) as remote_process_info:
      self.assertEqual(remote_process_info, PailgunProtocol.ProcessInitialized(31337, -31336))
      out = self.pailgun_client_session.process_session()

    self.assertEqual(out, 1729)
    self.assertEqual(self.fake_stdout.content, self.TEST_PAYLOAD * 2)
    self.assertEqual(self.fake_stderr.content, self.TEST_PAYLOAD * 3)
    self.mock_stdin_reader.start.assert_called_once_with()
    self.mock_stdin_reader.stop.assert_called_once_with()

  def test_process_session_bad_chunk(self):
    PailgunProtocol.send_pid(self.server_sock, 31337)
    PailgunProtocol.send_pgrp(self.server_sock, -31336)
    PailgunProtocol.send_start_reading_input(self.server_sock)
    PailgunProtocol.write_chunk(self.server_sock, self.BAD_CHUNK_TYPE, '')

    with self.pailgun_client_session.negotiate(
        self.TEST_WORKING_DIR,
        self.TEST_MAIN_CLASS,
        *self.TEST_ARGUMENTS,
        **self.TEST_ENVIRON) as remote_process_info:
      self.assertEqual(remote_process_info, PailgunProtocol.ProcessInitialized(31337, -31336))

      err_rx = re.escape('invalid chunk type: {}'.format(self.BAD_CHUNK_TYPE))
      with self.assertRaisesRegexp(NailgunProtocol.InvalidChunkType, err_rx):
        self.pailgun_client_session.process_session()

    self.mock_stdin_reader.start.assert_called_once_with()
    self.mock_stdin_reader.stop.assert_called_once_with()

  def test_execute(self):
    PailgunProtocol.send_pid(self.server_sock, 31337)
    PailgunProtocol.send_pgrp(self.server_sock, -31336)
    PailgunProtocol.send_start_reading_input(self.server_sock)
    PailgunProtocol.send_exit_with_code(self.server_sock, self.TEST_EXIT_CODE)

    with self.pailgun_client_session.negotiate(
        self.TEST_WORKING_DIR,
        self.TEST_MAIN_CLASS,
        *self.TEST_ARGUMENTS,
        **self.TEST_ENVIRON
    ) as remote_process_info:
      self.assertEqual(remote_process_info, PailgunProtocol.ProcessInitialized(31337, -31336))
      out = self.pailgun_client_session.process_session()

    self.assertEqual(out, self.TEST_EXIT_CODE)
    self.mock_stdin_reader.start.assert_called_once_with()
    self.mock_stdin_reader.stop.assert_called_once_with()


class TestPailgunClient(unittest.TestCase):
  def setUp(self):
    self.pailgun_client = PailgunClient()

  @mock.patch('pants.java.nailgun_client.RecvBufferedSocket', **PATCH_OPTS)
  def test_try_connect(self, mock_socket_cls):
    mock_socket = mock.Mock()
    mock_socket_cls.return_value = mock_socket

    self.assertEqual(self.pailgun_client.connect_socket(), mock_socket)

    self.assertEqual(mock_socket_cls.call_count, 1)
    mock_socket.connect.assert_called_once_with(
      (PailgunClient.DEFAULT_NG_HOST, PailgunClient.DEFAULT_NG_PORT)
    )

  @mock.patch('pants.java.nailgun_client.RecvBufferedSocket', **PATCH_OPTS)
  def test_try_connect_socket_error(self, mock_socket_cls):
    mock_socket = mock.Mock()
    mock_socket.connect.side_effect = socket.error()
    mock_socket_cls.return_value = mock_socket

    with self.assertRaises(PailgunClient.NailgunConnectionError):
      self.pailgun_client.connect_socket()

  @mock.patch.object(PailgunClient, 'connect_socket', **PATCH_OPTS)
  @mock.patch('pants.java.nailgun_client.PailgunClientSession', **PATCH_OPTS)
  def test_execute(self, mock_session, mock_try_connect):
    self.pailgun_client.execute('test')
    self.assertEqual(mock_try_connect.call_count, 1)
    self.assertEqual(mock_session.call_count, 1)

  @mock.patch.object(PailgunClient, 'connect_socket', **PATCH_OPTS)
  @mock.patch('pants.java.nailgun_client.PailgunClientSession', **PATCH_OPTS)
  def test_execute_propagates_connection_error_on_connect(self, mock_session, mock_try_connect):
    mock_try_connect.side_effect = PailgunClient.NailgunConnectionError(
      '127.0.0.1:31337',
      31337,
      -31336,
      Exception('oops'),
      None
    )

    with self.assertRaises(PailgunClient.NailgunConnectionError):
      self.pailgun_client.execute('test')

  @mock.patch.object(PailgunClient, 'connect_socket', **PATCH_OPTS)
  @mock.patch('pants.java.nailgun_client.PailgunClientSession', **PATCH_OPTS)
  def test_execute_socketerror_on_execute(self, mock_session, mock_try_connect):
    mock_session.return_value.negotiate.side_effect = socket.error('oops')

    with self.assertRaises(PailgunClient.NailgunError):
      self.pailgun_client.execute('test')

  @mock.patch.object(PailgunClient, 'connect_socket', **PATCH_OPTS)
  @mock.patch('pants.java.nailgun_client.PailgunClientSession', **PATCH_OPTS)
  def test_execute_protocolerror_on_execute(self, mock_session, mock_try_connect):
    mock_session.return_value.ProtocolError = NailgunProtocol.ProtocolError
    mock_session.return_value.negotiate.side_effect = NailgunProtocol.ProtocolError('oops')

    with self.assertRaises(PailgunClient.NailgunError):
      self.pailgun_client.execute('test')

  def test_repr(self):
    self.assertIsNotNone(repr(self.pailgun_client))

  @mock.patch('os.kill', **PATCH_OPTS)
  def test_send_control_c(self, mock_kill):
    self.pailgun_client._last_remote_process_info = PailgunProtocol.ProcessInitialized(
      pid=31337, pgrp=-31336)
    self.pailgun_client.send_control_c()
    mock_kill.assert_any_call(31337, signal.SIGINT)
    mock_kill.assert_any_call(-31336, signal.SIGINT)

  @mock.patch('os.kill', **PATCH_OPTS)
  def test_send_terminate(self, mock_kill):
    self.pailgun_client._last_remote_process_info = PailgunProtocol.ProcessInitialized(
      pid=31337, pgrp=-31336)
    self.pailgun_client.send_terminate()
    mock_kill.assert_any_call(31337, signal.SIGTERM)
    mock_kill.assert_any_call(-31336, signal.SIGTERM)
