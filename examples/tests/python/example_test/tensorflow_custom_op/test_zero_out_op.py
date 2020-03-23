# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import tensorflow as tf

from example.tensorflow_custom_op.zero_out_custom_op import zero_out_module


# This code is from the guide in https://www.tensorflow.org/guide/extend/op.
class ZeroOutTest(tf.test.TestCase):
    def test_zero_out(self):
        with self.cached_session():
            result = zero_out_module().zero_out([5, 4, 3, 2, 1])
            self.assertAllEqual(result.eval(), [5, 0, 0, 0, 0])
