# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import inspect
import io
import time
import unittest
import unittest.mock

from pants.java.nailgun_io import NailgunStreamWriter, Pipe, PipedNailgunStreamWriter
from pants.java.nailgun_protocol import ChunkType, NailgunProtocol


PATCH_OPTS = dict(autospec=True, spec_set=True)


class TestNailgunStreamWriter(unittest.TestCase):
    def setUp(self):
        self.in_fd = -1
        self.mock_socket = unittest.mock.Mock()
        self.writer = NailgunStreamWriter(
            (self.in_fd,), self.mock_socket, (ChunkType.STDIN,), ChunkType.STDIN_EOF
        )

    def test_stop(self):
        self.assertFalse(self.writer.is_stopped)
        self.writer.stop()
        self.assertTrue(self.writer.is_stopped)
        self.writer.run()

    def test_startable(self):
        self.assertTrue(inspect.ismethod(self.writer.start))

    @unittest.mock.patch("select.select")
    def test_run_stop_on_error(self, mock_select):
        mock_select.return_value = ([], [], [self.in_fd])
        self.writer.run()
        self.assertFalse(self.writer.is_alive())
        self.assertEqual(mock_select.call_count, 1)

    @unittest.mock.patch("os.read")
    @unittest.mock.patch("select.select")
    @unittest.mock.patch.object(NailgunProtocol, "write_chunk")
    def test_run_read_write(self, mock_writer, mock_select, mock_read):
        mock_select.side_effect = [([self.in_fd], [], []), ([self.in_fd], [], [])]
        mock_read.side_effect = [b"A" * 300, b""]  # Simulate EOF.

        # Exercise NailgunStreamWriter.running() and .run() simultaneously.
        inc = 0
        with self.writer.running():
            while self.writer.is_alive():
                time.sleep(0.01)
                inc += 1
                if inc >= 1000:
                    raise Exception("waited too long.")

        self.assertFalse(self.writer.is_alive())

        mock_read.assert_called_with(-1, io.DEFAULT_BUFFER_SIZE)
        self.assertEqual(mock_read.call_count, 2)

        mock_writer.assert_has_calls(
            [
                unittest.mock.call(unittest.mock.ANY, ChunkType.STDIN, b"A" * 300),
                unittest.mock.call(unittest.mock.ANY, ChunkType.STDIN_EOF),
            ]
        )


class TestPipedNailgunStreamWriter(unittest.TestCase):
    def setUp(self):
        self.mock_socket = unittest.mock.Mock()

    @unittest.mock.patch("os.read")
    @unittest.mock.patch("select.select")
    @unittest.mock.patch.object(NailgunProtocol, "write_chunk")
    def test_auto_shutdown_on_write_end_closed(self, mock_writer, mock_select, mock_read):
        pipe = Pipe.create(False)
        test_data = [b"A"] * 1000 + [b""]
        mock_read.side_effect = test_data
        mock_select.side_effect = [([pipe.read_fd], [], [])] * len(test_data)

        writer = PipedNailgunStreamWriter(
            pipes=[pipe],
            socket=self.mock_socket,
            chunk_type=(ChunkType.STDOUT,),
            chunk_eof_type=None,
            buf_size=len(b"A"),
        )

        with writer.running():
            pipe.stop_writing()
            writer.join(1)
            self.assertFalse(writer.is_alive())

        mock_writer.assert_has_calls(
            [unittest.mock.call(unittest.mock.ANY, ChunkType.STDOUT, b"A")] * (len(test_data) - 1)
        )
