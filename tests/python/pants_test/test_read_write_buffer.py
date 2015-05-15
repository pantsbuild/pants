# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.rwbuf.read_write_buffer import InMemoryRWBuf


class ReadWriteBufferTest(unittest.TestCase):

  def test_closed_buffer_is_closed(self):
    buff = InMemoryRWBuf()
    buff.write('hello')
    buff.close()

    self.assertTrue(buff.is_closed())

  def test_read_from_buffer(self):
    buff = InMemoryRWBuf()
    buff.write('hello')

    ret = buff.read()

    self.assertEqual('hello', ret)
