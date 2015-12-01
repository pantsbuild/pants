# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import inspect
import io
import os
import socket
import time
import unittest

import mock

from pants.java.nailgun_io import NailgunStreamReader, NailgunStreamWriter
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


class TestNailgunStreamReader(unittest.TestCase):
  def setUp(self):
    self.in_fd = FakeFile()
    self.mock_socket = mock.Mock()
    self.reader = NailgunStreamReader(in_fd=self.in_fd, sock=self.mock_socket)

  def test_stop(self):
    self.assertFalse(self.reader.is_stopped)
    self.reader.stop()
    self.assertTrue(self.reader.is_stopped)
    self.reader.run()

  def test_startable(self):
    self.assertTrue(inspect.ismethod(self.reader.start))

  @mock.patch('select.select')
  def test_run_stop_on_error(self, mock_select):
    mock_select.return_value = ([], [], [self.in_fd])
    self.reader.run()
    self.assertTrue(self.reader.is_stopped)
    self.assertEquals(mock_select.call_count, 1)

  @mock.patch('os.read')
  @mock.patch('select.select')
  @mock.patch.object(NailgunProtocol, 'write_chunk')
  def test_run_read_write(self, mock_writer, mock_select, mock_read):
    mock_select.side_effect = [
      ([self.in_fd], [], []),
      ([self.in_fd], [], [])
    ]
    mock_read.side_effect = [
      b'A' * 300,
      b''          # Simulate EOF.
    ]

    # Exercise NailgunStreamReader.running() and .run() simultaneously.
    with self.reader.running():
      while not self.reader.is_stopped:
        time.sleep(0.01)

    self.assertTrue(self.reader.is_stopped)

    mock_read.assert_called_with(-1, io.DEFAULT_BUFFER_SIZE)
    self.assertEquals(mock_read.call_count, 2)

    self.mock_socket.shutdown.assert_called_once_with(socket.SHUT_WR)

    mock_writer.assert_has_calls([
      mock.call(mock.ANY, ChunkType.STDIN, b'A' * 300),
      mock.call(mock.ANY, ChunkType.STDIN_EOF)
    ])


class TestNailgunStreamWriter(unittest.TestCase):
  TEST_VALUE = '1729'

  def setUp(self):
    self.chunk_type = ChunkType.STDERR
    self.mock_socket = mock.Mock()
    self.writer = NailgunStreamWriter(self.mock_socket, self.chunk_type)

  @mock.patch.object(NailgunProtocol, 'write_chunk')
  def test_write(self, mock_writer):
    self.writer.write(self.TEST_VALUE)
    mock_writer.assert_called_once_with(self.mock_socket, self.chunk_type, self.TEST_VALUE)

  @mock.patch.object(NailgunProtocol, 'write_chunk')
  def test_write_broken_pipe_unmasked(self, mock_writer):
    mock_writer.side_effect = IOError(errno.EPIPE, os.strerror(errno.EPIPE))
    with self.assertRaises(IOError):
      self.writer.write(self.TEST_VALUE)

  @mock.patch.object(NailgunProtocol, 'write_chunk')
  def test_write_broken_pipe_masked(self, mock_writer):
    self.writer = NailgunStreamWriter(self.mock_socket, self.chunk_type, mask_broken_pipe=True)
    mock_writer.side_effect = IOError(errno.EPIPE, os.strerror(errno.EPIPE))
    self.writer.write(self.TEST_VALUE)

  def test_isatty(self):
    self.assertTrue(self.writer.isatty())

  def test_not_isatty(self):
    self.writer = NailgunStreamWriter(self.mock_socket, self.chunk_type, isatty=False)
    self.assertFalse(self.writer.isatty())

  def test_misc(self):
    self.writer.flush()
