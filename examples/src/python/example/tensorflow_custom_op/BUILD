# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TODO(#7059): add a page() for the README once it is easier to extend the docsite!

# See https://www.tensorflow.org/guide/extend/op!

ctypes_compatible_cpp_library(
  name='tensorflow-zero-out-op',
  dependencies=[
    'examples/3rdparty/python:tensorflow-framework',
  ],
  ctypes_native_library=native_artifact(lib_name='tensorflow-zero-out-operator'),
)

ctypes_compatible_cpp_library(
  name='tensorflow-zero-out-op-gpu',
  dependencies=[
    'examples/3rdparty/python:tensorflow-framework-gpu',
  ],
  ctypes_native_library=native_artifact(lib_name='tensorflow-zero-out-operator-gpu'),
)

# TODO: allow merging of this and a python_library() somehow! If we could make dependencies (such as
# tensorflow) into install_requires() with the SetupPy task somehow, this would be easy!
python_dist(
  name='tensorflow-zero-out-op-wrapper',
  sources=[
    'setup.py',
    '__init__.py',
    # TODO: we shouldn't have to introduce this second-level package, but I can't figure out how to
    # use wrap_zero_out_op.py at the top level!
    'wrap_lib/wrap_zero_out_op.py',
    'wrap_lib/__init__.py',
  ],
  dependencies=[
    ':tensorflow-zero-out-op',
  ],
)

# TODO: allow merging of this and a python_library() somehow! If we could make dependencies (such as
# tensorflow) into install_requires() with the SetupPy task somehow, this would be easy!
python_dist(
  name='tensorflow-zero-out-op-wrapper-gpu',
  sources=[
    'setup.py',
    '__init__.py',
    # TODO: we shouldn't have to introduce this second-level package, but I can't figure out how to
    # use wrap_zero_out_op.py at the top level!
    'wrap_lib/wrap_zero_out_op.py',
    'wrap_lib/__init__.py',
  ],
  dependencies=[
    ':tensorflow-zero-out-op-gpu',
  ],
)

python_library(
  name='tensorflow_custom_op',
  sources=['zero_out_custom_op.py'],
  dependencies=[
    'examples/3rdparty/python:tensorflow',
    ':tensorflow-zero-out-op-wrapper',
  ],
)

python_library(
  name='tensorflow_custom_op_gpu',
  sources=['zero_out_custom_op.py'],
  dependencies=[
    'examples/3rdparty/python:tensorflow-gpu',
    ':tensorflow-zero-out-op-wrapper-gpu',
  ],
)

python_binary(
  name='zero-out-custom-op-hello-world',
  source='zero_out_hello_world.py',
  dependencies=[':tensorflow_custom_op'],
  platforms=['linux_x86_64', 'current'],
)

python_binary(
  name='zero-out-custom-op-hello-world-gpu',
  source='zero_out_hello_world.py',
  dependencies=[':tensorflow_custom_op_gpu'],
  platforms=['linux_x86_64'],
)
