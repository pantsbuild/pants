# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import socket
import unittest
from SocketServer import TCPServer

import mock

from pants.java.nailgun_protocol import ChunkType, NailgunProtocol
from pants.pantsd.pailgun_server import PailgunHandler, PailgunServer


PATCH_OPTS = dict(autospec=True, spec_set=True)


class TestPailgunServer(unittest.TestCase):
  def setUp(self):
    self.mock_handler_inst = mock.Mock()
    self.mock_runner_factory = mock.Mock(side_effect=Exception('this should never be called'))
    self.mock_handler_class = mock.Mock(return_value=self.mock_handler_inst)
    with mock.patch.object(PailgunServer, 'server_bind'), \
         mock.patch.object(PailgunServer, 'server_activate'):
      self.server = PailgunServer(
        server_address=('0.0.0.0', 0),
        runner_factory=self.mock_runner_factory,
        handler_class=self.mock_handler_class
      )

  @mock.patch.object(TCPServer, 'server_bind', **PATCH_OPTS)
  def test_server_bind(self, mock_tcpserver_bind):
    mock_sock = mock.Mock()
    mock_sock.getsockname.return_value = ('0.0.0.0', 31337)
    self.server.socket = mock_sock
    self.server.server_bind()
    self.assertEquals(self.server.server_port, 31337)
    self.assertIs(mock_tcpserver_bind.called, True)

  @mock.patch.object(PailgunServer, 'close_request', **PATCH_OPTS)
  def test_process_request(self, mock_close_request):
    mock_request = mock.Mock()
    self.server.process_request(mock_request, ('1.2.3.4', 31338))
    self.assertIs(self.mock_handler_inst.handle_request.called, True)
    mock_close_request.assert_called_once_with(self.server, mock_request)

  @mock.patch.object(PailgunServer, 'shutdown_request', **PATCH_OPTS)
  def test_process_request_error(self, mock_shutdown_request):
    mock_request = mock.Mock()
    self.mock_handler_inst.handle_request.side_effect = AttributeError('oops')
    self.server.process_request(mock_request, ('1.2.3.4', 31338))
    self.assertIs(self.mock_handler_inst.handle_request.called, True)
    self.assertIs(self.mock_handler_inst.handle_error.called, True)
    mock_shutdown_request.assert_called_once_with(self.server, mock_request)


class TestPailgunHandler(unittest.TestCase):
  def setUp(self):
    self.client_sock, self.server_sock = socket.socketpair()
    self.mock_socket = mock.Mock()
    self.mock_server = mock.create_autospec(PailgunServer, spec_set=True)
    self.handler = PailgunHandler(
      self.server_sock,
      self.client_sock.getsockname()[:2],
      self.mock_server
    )

  def test_handle_error(self):
    self.handler.handle_error()
    last_chunk_type, last_payload = list(NailgunProtocol.iter_chunks(self.client_sock))[-1]
    self.assertEquals(last_chunk_type, ChunkType.EXIT)
    self.assertEquals(bytes(last_payload), '1')

  @mock.patch.object(PailgunHandler, '_run_pants', **PATCH_OPTS)
  def test_handle_request(self, mock_run_pants):
    NailgunProtocol.send_request(self.client_sock, '/test', './pants', 'help-advanced')
    self.handler.handle_request()
    self.assertIs(mock_run_pants.called, True)
