# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.util.contextutil import temporary_file
from pants.util.fileutil import atomic_copy


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
