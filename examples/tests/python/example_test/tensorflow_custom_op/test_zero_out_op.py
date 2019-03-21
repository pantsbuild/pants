# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import sys
import unittest

import tensorflow as tf

from example.tensorflow_custom_op.zero_out_custom_op import zero_out_module


# This code is from the guide in https://www.tensorflow.org/guide/extend/op.
class ZeroOutTest(tf.test.TestCase):

  @unittest.skipIf(sys.version_info[0:2] == (3, 7), "See https://github.com/pantsbuild/pants/issues/7417.")
  def test_zero_out(self):
    with self.test_session():
      result = zero_out_module().zero_out([5, 4, 3, 2, 1])
      self.assertAllEqual(result.eval(), [5, 0, 0, 0, 0])
