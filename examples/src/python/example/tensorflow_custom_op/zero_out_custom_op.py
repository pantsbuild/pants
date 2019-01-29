# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import tensorflow as tf
from future.utils import binary_type
# TODO: It would be great if we could maintain the example.tensorflow_custom_op package prefix for
# this python_dist()!
from wrap_lib.wrap_zero_out_op import zero_out_op_lib_path


# We make this a function in order to lazily load the op library.
def zero_out_module():
  return tf.load_op_library(binary_type(zero_out_op_lib_path.encode()))
