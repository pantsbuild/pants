# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.base.run_info import RunInfo
from pants.util.contextutil import temporary_file_path


class RunInfoTest(unittest.TestCase):
  def test_run_info_read(self):
    with temporary_file_path() as tmppath:
      with open(tmppath, 'w') as tmpfile:
        tmpfile.write('foo:bar\n baz :qux quux')
      ri = RunInfo(tmppath)
      self.assertEquals(ri.path(), tmppath)

      # Test get_info access.
      self.assertEquals(ri.get_info('foo'), 'bar')
      self.assertEquals(ri.get_info('baz'), 'qux quux')
      self.assertIsNone(ri.get_info('nonexistent'))

      # Test dict-like access.
      self.assertEquals(ri['foo'], 'bar')
      self.assertEquals(ri['baz'], 'qux quux')

  def test_write_run_info(self):
    with temporary_file_path() as tmppath:
      ri = RunInfo(tmppath)
      ri.add_info('key1', 'val1')
      ri.add_infos(('key2', ' val2'), (' key3 ', 'val3 '))
      self.assertEquals({'key1': 'val1', 'key2': 'val2', 'key3': 'val3'}, ri.get_as_dict())

      with open(tmppath, 'r') as tmpfile:
        contents = tmpfile.read()
      self.assertEquals('key1: val1\nkey2: val2\nkey3: val3\n', contents)
