# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.contextutil import temporary_file, temporary_file_path
from pants.util.fileutil import atomic_copy, create_size_estimators


class FileutilTest(unittest.TestCase):
  def test_atomic_copy(self):
    with temporary_file() as src:
      src.write(src.name)
      src.flush()
      with temporary_file() as dst:
        atomic_copy(src.name, dst.name)
        dst.close()
        with open(dst.name) as new_dst:
          self.assertEquals(src.name, new_dst.read())

  def test_line_count_estimator(self):
    with temporary_file_path() as src:
      self.assertEqual(create_size_estimators()['linecount']([src]), 0)
