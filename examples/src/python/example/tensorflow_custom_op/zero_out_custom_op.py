# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TODO: It would be great if we could maintain the example.tensorflow_custom_op package prefix for
# this python_dist()!

import tensorflow as tf
from wrap_lib.wrap_zero_out_op import zero_out_op_lib_path


# We make this a function in order to lazily load the op library.
def zero_out_module():
    return tf.load_op_library(zero_out_op_lib_path)
