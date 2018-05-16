# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import inspect
import io
import time
import unittest

import mock

from pants.java.nailgun_io import NailgunStreamWriter
from pants.java.nailgun_protocol import ChunkType, NailgunProtocol


PATCH_OPTS = dict(autospec=True, spec_set=True)


class TestNailgunStreamWriter(unittest.TestCase):
  def setUp(self):
    self.in_fd = -1
    self.mock_socket = mock.Mock()
    self.writer = NailgunStreamWriter(
      (self.in_fd,),
      self.mock_socket,
      (ChunkType.STDIN,),
      ChunkType.STDIN_EOF
    )

  def test_stop(self):
    self.assertFalse(self.writer.is_stopped)
    self.writer.stop()
    self.assertTrue(self.writer.is_stopped)
    self.writer.run()

  def test_startable(self):
    self.assertTrue(inspect.ismethod(self.writer.start))

  @mock.patch('select.select')
  def test_run_stop_on_error(self, mock_select):
    mock_select.return_value = ([], [], [self.in_fd])
    self.writer.run()
    self.assertFalse(self.writer.is_alive())
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

    # Exercise NailgunStreamWriter.running() and .run() simultaneously.
    inc = 0
    with self.writer.running():
      while self.writer.is_alive():
        time.sleep(0.01)
        inc += 1
        if inc >= 1000:
          raise Exception('waited too long.')

    self.assertFalse(self.writer.is_alive())

    mock_read.assert_called_with(-1, io.DEFAULT_BUFFER_SIZE)
    self.assertEquals(mock_read.call_count, 2)

    mock_writer.assert_has_calls([
      mock.call(mock.ANY, ChunkType.STDIN, b'A' * 300),
      mock.call(mock.ANY, ChunkType.STDIN_EOF)
    ])
