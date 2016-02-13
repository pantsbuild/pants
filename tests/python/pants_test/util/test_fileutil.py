# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import random
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
        self.assertEqual(os.stat(src.name).st_mode, os.stat(dst.name).st_mode)

  def test_line_count_estimator(self):
    with temporary_file_path() as src:
      self.assertEqual(create_size_estimators()['linecount']([src]), 0)

  def test_random_estimator(self):
    seedValue = 5
    # The number chosen for seedValue doesn't matter, so long as it is the same for the call to
    # generate a random test number and the call to create_size_estimators.
    random.seed(seedValue)
    rand = random.randint(0, 10000)
    random.seed(seedValue)
    with temporary_file_path() as src:
      self.assertEqual(create_size_estimators()['random']([src]), rand)
