# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.fs.fs import safe_filename


class SafeFilenameTest(unittest.TestCase):
  class FixedDigest(object):
    def __init__(self, size):
      self._size = size

    def update(self, value):
      pass

    def hexdigest(self):
      return self._size * '*'

  def test_bad_name(self):
    with self.assertRaises(ValueError):
      safe_filename(os.path.join('more', 'than', 'a', 'name.game'))

  def test_noop(self):
    self.assertEqual('jack.jill', safe_filename('jack', '.jill', max_length=9))
    self.assertEqual('jack.jill', safe_filename('jack', '.jill', max_length=100))

  def test_shorten(self):
    self.assertEqual('**.jill',
                     safe_filename('jack', '.jill', digest=self.FixedDigest(2), max_length=8))

  def test_shorten_fail(self):
    with self.assertRaises(ValueError):
      safe_filename('jack', '.beanstalk', digest=self.FixedDigest(3), max_length=12)
