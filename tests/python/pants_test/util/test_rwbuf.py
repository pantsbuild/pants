# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.util.contextutil import temporary_file_path
from pants.util.rwbuf import FileBackedRWBuf, StringWriter


class StringWriterTest(unittest.TestCase):
    def test_writes_string(self):
        with temporary_file_path() as p:
            fb = FileBackedRWBuf(p)
            try:
                sw = StringWriter(fb)
                sw.write("\u2764 Curious Zelda")
            finally:
                fb.close()
            with open(p, "rb") as f:
                contents = f.read()
                self.assertEquals(contents, b"\xe2\x9d\xa4 Curious Zelda")

    def test_rejects_binary(self):
        with temporary_file_path() as p:
            fb = FileBackedRWBuf(p)
            sw = StringWriter(fb)
            try:
                with self.assertRaises(ValueError):
                    sw.write(b"Curious Zelda")
            finally:
                fb.close()

    def test_can_write_binary_to_buffer(self):
        with temporary_file_path() as p:
            fb = FileBackedRWBuf(p)
            try:
                sw = StringWriter(fb)
                sw.write("\u2764")
                sw.buffer.write(b" Curious")
                sw.write(" Zelda")
            finally:
                fb.close()
            with open(p, "rb") as f:
                contents = f.read()
                self.assertEquals(contents, b"\xe2\x9d\xa4 Curious Zelda")
