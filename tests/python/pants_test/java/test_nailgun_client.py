# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re
import signal
import socket
import unittest
from builtins import object
from contextlib import contextmanager

import mock
from future.utils import binary_type

from pants.java.nailgun_client import NailgunClientRequest, NailgunClientSession, PailgunClient
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
    self.fake_stdout = FakeFile()
    self.fake_stderr = FakeFile()

    self.mock_stdin_reader = mock.create_autospec(NailgunStreamWriter, spec_set=True)
    self.mock_stdin_reader.is_alive.side_effect = [False, True]

  def _pailgun_client(self):
    nailgun_client_request = NailgunClientRequest(
      ins=None,
      out=self.fake_stdout,
      err=self.fake_stderr,
    )
    pailgun_client = PailgunClient(nailgun_client_request)
    return pailgun_client

  @contextmanager
  def _pailgun_client_session(self):
    client_sock, server_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    pailgun_client = self._pailgun_client()
    pailgun_client._get_socket = lambda: client_sock
    with pailgun_client.initiate_new_client_session() as pg_session:
      pg_session._request = pg_session._request.copy(input_writer=self.mock_stdin_reader)
      try:
        yield (pg_session, client_sock, server_sock)
      finally:
        client_sock.close()
        server_sock.close()

  @contextmanager
  def _remote_pailgun_handle(self):
    client_sock, server_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    pailgun_client = self._pailgun_client()
    pailgun_client._get_socket = lambda: client_sock
    exe_req = NailgunClientSession.NailgunClientSessionExecutionRequest(
      main_class=binary_type(self.TEST_MAIN_CLASS),
      cwd=binary_type(self.TEST_WORKING_DIR),
      arguments=tuple(self.TEST_ARGUMENTS),
      environment=self.TEST_ENVIRON,
    )
    PailgunProtocol.send_pid(server_sock, 31337)
    PailgunProtocol.send_pgrp(server_sock, -31336)
    with pailgun_client.remote_pants_session(exe_req) as remote_handle:
      pg_session = remote_handle.session
      pg_session._request = pg_session._request.copy(input_writer=self.mock_stdin_reader)
      try:
        self.assertEqual(remote_handle.remote_process_info,
                         PailgunProtocol.ProcessInitialized(31337, -31336))
        yield (remote_handle, client_sock, server_sock)
      finally:
        client_sock.close()
        server_sock.close()

  def test_input_writer_start_stop(self):
    with self._pailgun_client_session() as (pg_session, _, _):
      pg_session._maybe_start_input_writer()
      self.mock_stdin_reader.start.assert_called_once_with()
      pg_session._maybe_stop_input_writer()
      self.mock_stdin_reader.stop.assert_called_once_with()

  def test_input_writer_noop(self):
    with self._pailgun_client_session() as (pg_session, _, _):
      pg_session._request._input_writer = None
      pg_session._maybe_start_input_writer()
      pg_session._maybe_stop_input_writer()

  def test_process_session(self):
    with self._remote_pailgun_handle() as (remote_handle, _, server_sock):
      PailgunProtocol.send_start_reading_input(server_sock)
      PailgunProtocol.send_stdout(server_sock, self.TEST_PAYLOAD)
      PailgunProtocol.send_stderr(server_sock, self.TEST_PAYLOAD)
      PailgunProtocol.send_stderr(server_sock, self.TEST_PAYLOAD)
      PailgunProtocol.send_stdout(server_sock, self.TEST_PAYLOAD)
      PailgunProtocol.send_stderr(server_sock, self.TEST_PAYLOAD)
      PailgunProtocol.send_exit_with_code(server_sock, 1729)
      out = remote_handle.session.process_session()

    self.assertEqual(out, 1729)
    self.assertEqual(self.fake_stdout.content, self.TEST_PAYLOAD * 2)
    self.assertEqual(self.fake_stderr.content, self.TEST_PAYLOAD * 3)
    self.mock_stdin_reader.start.assert_called_once_with()
    self.mock_stdin_reader.stop.assert_called_once_with()

  def test_process_session_bad_chunk(self):
    with self._remote_pailgun_handle() as (remote_handle, _, server_sock):
      PailgunProtocol.send_start_reading_input(server_sock)
      PailgunProtocol.write_chunk(server_sock, self.BAD_CHUNK_TYPE, '')

      err_rx = re.escape('invalid chunk type: {}'.format(self.BAD_CHUNK_TYPE))
      with self.assertRaisesRegexp(NailgunProtocol.ProtocolError, err_rx):
        remote_handle.session.process_session()

    self.mock_stdin_reader.start.assert_called_once_with()
    self.mock_stdin_reader.stop.assert_called_once_with()

  def test_execute(self):
    with self._remote_pailgun_handle() as (remote_handle, _, server_sock):
      PailgunProtocol.send_start_reading_input(server_sock)
      PailgunProtocol.send_exit_with_code(server_sock, self.TEST_EXIT_CODE)
      out = remote_handle.session.process_session()

    self.assertEqual(out, self.TEST_EXIT_CODE)
    self.mock_stdin_reader.start.assert_called_once_with()
    self.mock_stdin_reader.stop.assert_called_once_with()


class TestPailgunClient(unittest.TestCase):
  BAD_CHUNK_TYPE = b';'
  TEST_PAYLOAD = b't e s t'
  TEST_EXIT_CODE = 13
  TEST_WORKING_DIR = '/test_working_dir'
  TEST_MAIN_CLASS = 'test_main_class'
  TEST_ARGUMENTS = [b't', b'e', b's', b't']
  TEST_ENVIRON = dict(TEST_ENV_VAR='xyz')

  def _pailgun_client(self):
    request = NailgunClientRequest()
    client = PailgunClient(request)
    return client

  @contextmanager
  def _execute_pailgun_client(self, *arguments):
    pg_client = self._pailgun_client()
    exe_req = NailgunClientSession.NailgunClientSessionExecutionRequest(
      main_class=binary_type(self.TEST_MAIN_CLASS),
      cwd=binary_type(self.TEST_WORKING_DIR),
      arguments=tuple(arguments),
      environment=self.TEST_ENVIRON,
    )
    with pg_client.remote_pants_session(exe_req) as handle:
      handle.session.process_session()
      yield handle

  def test_try_connect_socket_error(self):
    mock_socket = mock.Mock()
    mock_socket.connect.side_effect = socket.error()
    pg_client = self._pailgun_client()
    pg_client._get_socket = lambda: mock_socket.connect()

    with self.assertRaises(PailgunClient.NailgunConnectionError):
      pg_client.connect_socket()

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
